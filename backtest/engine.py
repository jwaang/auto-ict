"""Walk-forward backtesting engine for ICT strategies.

Iterates through entry-timeframe bars, runs the full ICT detection pipeline
at each step with point-in-time data (no look-ahead bias), and simulates
trades using the existing position/risk management modules.
"""

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd

from zoneinfo import ZoneInfo

from backtest import params
from backtest.intrabar import Intrabar
from backtest.rules import decide_trade
from backtest.strategies import get_strategy
from config import (
    BACKTEST_SMC_SWING_LENGTH,
    MAX_DRAWDOWN_PCT,
    MIN_CONFLUENCE_SCORE,
    STARTING_BALANCE,
)
from data.historical import build_multi_timeframe, get_windowed_data
from ict.confluence import analyze_multi_timeframe
from ict.killzones import is_crypto as _is_crypto_fn
from ict.smc_adapter import set_swing_length_override
from trading.account import Account
from trading.positions import Position, PositionManager

_ET = ZoneInfo("America/New_York")

# Session end hours (ET) — force close all non-crypto positions
_SESSION_END_HOUR = 16  # 4:00 PM ET (ES RTH close)
from trading.risk import validate_trade


@dataclass
class BacktestResult:
    """Results from a backtest run."""
    trades: list[dict] = field(default_factory=list)
    equity_curve: list[dict] = field(default_factory=list)
    no_trade_decisions: int = 0
    low_confluence_skips: int = 0
    unaffordable_skips: int = 0
    trades_after_break: int = 0  # entered on a bar that opened after a session gap
    bars_processed: int = 0
    start_time: str = ""
    end_time: str = ""
    duration_seconds: float = 0
    starting_balance: float = 0
    final_balance: float = 0
    max_drawdown_pct: float = 0.0  # mark-to-market, includes open positions
    rejections: dict = field(default_factory=dict)  # why bars did not become trades
    parameters: dict = field(default_factory=dict)


_NUMBERS = re.compile(r"-?\d+\.?\d*")


def _record_excursion(trade: dict, intrabar, exit_time) -> None:
    """Attach favourable and adverse excursion in R to a closed trade.

    Pure measurement — it changes nothing about the trade. The question it answers
    is whether the target was ever reachable: if MFE rarely reaches the target's R
    even on winners, the geometry is wrong by construction.
    """
    if not trade.get("entry_time") or trade.get("stop_loss") is None:
        return
    got = intrabar.excursion(
        trade["direction"], trade["entry_price"], trade["stop_loss"],
        pd.Timestamp(trade["entry_time"]), pd.Timestamp(exit_time),
    )
    trade.update(got)


def _accumulate_costs(trade: dict, fill: dict):
    """Add a fill's cost components onto the trade record.

    Partial closes contribute more than once, so these accumulate rather than
    overwrite. Recording them is what turns "costs ate the edge" from an
    inference into a measurement.
    """
    for key in ("gross_pnl", "costs"):
        trade[key] = round((trade.get(key) or 0) + (fill.get(key) or 0), 2)


def _count(result: "BacktestResult", reason: str):
    """Tally why a bar produced no trade.

    Numbers are stripped so "R:R 1.3 < 2.0" and "R:R 1.7 < 2.0" land in one
    bucket. Without this histogram, finding out which gate is blocking a run
    needs an ad-hoc probe — which is how the bias bug went unnoticed.
    """
    key = _NUMBERS.sub("N", reason).strip() or "unknown"
    result.rejections[key] = result.rejections.get(key, 0) + 1


# Default warmup and step values per entry timeframe
_ENTRY_TF_DEFAULTS = {
    "1min":  {"warmup": 1000, "step": 1},    # analyze every bar
    "5min":  {"warmup": 500,  "step": 1},    # analyze every bar
    "15min": {"warmup": 200,  "step": 1},    # analyze every bar
    "30min": {"warmup": 100,  "step": 1},    # analyze every bar
    "1h":    {"warmup": 50,   "step": 1},    # analyze every bar
}


def run_backtest(
    df_1m: pd.DataFrame,
    starting_balance: float = STARTING_BALANCE,
    min_score: int = MIN_CONFLUENCE_SCORE,
    ticker: str = "ES",
    entry_tf: str = "15min",
    step_bars: int | None = None,
    warmup_bars: int | None = None,
    progress_every: int = 500,
    strategy: str = "default",
    trade_start: pd.Timestamp | None = None,
    trade_end: pd.Timestamp | None = None,
) -> BacktestResult:
    """Run a walk-forward backtest on historical 1-minute data.

    Args:
        df_1m: 1-minute OHLCV DataFrame (continuous contract)
        starting_balance: Initial account balance
        min_score: Minimum confluence score to take trades
        ticker: Ticker symbol for display/logging
        entry_tf: Entry timeframe ("1min", "5min", "15min", etc.)
        step_bars: Process every Nth entry bar (auto-calculated if None)
        warmup_bars: Minimum entry bars before starting (auto-calculated if None)
        progress_every: Print progress every N bars
        strategy: Strategy name ("default", "ict_2022", "silver_bullet")
        trade_start: If set, don't open new trades before this timestamp.
                     Data before this is used for HTF warmup only.
        trade_end: If set, stop opening new trades after this timestamp.
                   Open positions are allowed to close naturally (SL/TP/session-end).

    Returns:
        BacktestResult with all trades, equity curve, and stats
    """
    # Auto-calculate defaults from entry timeframe
    defaults = _ENTRY_TF_DEFAULTS.get(entry_tf, {"warmup": 200, "step": 4})
    if warmup_bars is None:
        warmup_bars = defaults["warmup"]
    if step_bars is None:
        step_bars = defaults["step"]

    t0 = time.time()

    # Swing lengths are overridable per run so the backtest/live divergence can
    # be swept rather than assumed. Wrapped in try/finally to guarantee
    # restoration even on exceptions.
    set_swing_length_override(params.get("smc_swing_length", BACKTEST_SMC_SWING_LENGTH))
    try:
        return _run_backtest_inner(
            df_1m, starting_balance, min_score, ticker,
            entry_tf, step_bars, warmup_bars, progress_every, t0,
            strategy, trade_start, trade_end,
        )
    finally:
        set_swing_length_override(None)


def _run_backtest_inner(
    df_1m, starting_balance, min_score, ticker,
    entry_tf, step_bars, warmup_bars, progress_every, t0,
    strategy="default", trade_start=None, trade_end=None,
) -> BacktestResult:
    """Inner backtest loop, separated so run_backtest can wrap in try/finally."""
    # Build all timeframes from 1m data
    print(f"  Resampling 1m data to all timeframes (entry={entry_tf})...")
    all_tf = build_multi_timeframe(df_1m, entry_tf=entry_tf)
    entry_bars = all_tf["entry"]

    # Bars that open after a break — the daily halt, a weekend or a holiday.
    # Real gaps, but the FVG and displacement detectors read each as a signal,
    # so count how many trades start on one.
    bar_gap = entry_bars["timestamp"].diff()
    after_break = (bar_gap > bar_gap.mode().iloc[0]).to_numpy() if len(entry_bars) > 1 else None

    # One-minute view for excursion measurement and, when enabled, for resolving
    # which barrier a coarse bar hit first.
    intrabar = Intrabar(df_1m)

    print(f"  Entry bars: {len(entry_bars)}, Warmup: {warmup_bars}, Step: {step_bars}")
    print(f"  Bars to process: ~{(len(entry_bars) - warmup_bars) // step_bars}")

    # Initialize account and position manager
    account = Account(
        starting_balance=starting_balance,
        drawdown_limit_pct=params.get("drawdown_limit_pct", MAX_DRAWDOWN_PCT),
    )
    pm = PositionManager()

    # Record every input, not a subset — a sweep row that cannot identify the
    # config that produced it is useless.
    result = BacktestResult(
        starting_balance=starting_balance,
        parameters={
            "ticker": ticker,
            "strategy": strategy,
            "entry_tf": entry_tf,
            "min_score": min_score,
            "step_bars": step_bars,
            "warmup_bars": warmup_bars,
            "starting_balance": starting_balance,
            "trade_start": str(trade_start) if trade_start is not None else None,
            "trade_end": str(trade_end) if trade_end is not None else None,
            "overrides": params.active(),
        },
    )

    result.equity_curve.append({
        "timestamp": str(entry_bars.iloc[warmup_bars]["timestamp"]),
        "balance": starting_balance,
        "event": "start",
    })

    # HTF analysis cache — passed to analyze_multi_timeframe to avoid
    # re-analyzing bias/swing/setup every step when their latest bar hasn't changed
    _analysis_cache = {}

    # Walk forward through entry bars
    for i in range(warmup_bars, len(entry_bars)):
        bar = entry_bars.iloc[i]
        current_time = bar["timestamp"]
        candle = {"high": bar["high"], "low": bar["low"], "close": bar["close"]}

        # Check open positions for SL/TP fills on EVERY bar (before session-end,
        # so a bar that hits SL/TP records the real fill, not a synthetic close)
        fills = pm.check_fills(candle)
        for fill in fills:
            pnl = fill["pnl_dollars"]
            account.update_balance(pnl)
            fill["timestamp"] = str(current_time)

            is_partial = fill.get("partial", False)

            for t in result.trades:
                if t["id"] == fill["position_id"]:
                    if is_partial:
                        # Partial fill — accumulate P&L, don't close the trade
                        if "partial_fills" not in t:
                            t["partial_fills"] = []
                        t["partial_fills"].append(fill)
                        existing_pnl = t.get("pnl_dollars") or 0
                        t["pnl_dollars"] = round(existing_pnl + pnl, 2)
                        _accumulate_costs(t, fill)
                    else:
                        # Full close
                        t["exit_price"] = fill["exit_price"]
                        t["exit_reason"] = fill["exit_reason"]
                        t["pnl_dollars"] = round((t.get("pnl_dollars") or 0) + pnl, 2)
                        _accumulate_costs(t, fill)
                        t["pnl_pct"] = fill["pnl_pct"]
                        t["rr_achieved"] = fill["rr_achieved"]
                        t["exit_time"] = str(current_time)
                        t["status"] = "CLOSED"
                        _record_excursion(t, intrabar, current_time)
                    break

            result.equity_curve.append({
                "timestamp": str(current_time),
                "balance": round(account.balance, 2),
                "pnl": round(pnl, 2),
                "event": fill["exit_reason"],
            })

        # Mark to market so drawdown and the circuit breaker see open risk,
        # not just the balance left behind by closed trades.
        account.mark_equity(account.balance + pm.unrealized_pnl(bar["close"]))

        # Circuit breaker: force-close ALL positions when drawdown limit hit
        if account.is_circuit_breaker_hit() and pm.get_open_count() > 0:
            account.trigger_circuit_breaker()
            for pos in pm.get_open_positions():
                fill = pm.close_position_manual(pos.id, bar["close"], "CIRCUIT_BREAKER")
                if fill:
                    account.update_balance(fill["pnl_dollars"])
                    for t in result.trades:
                        if t["id"] == pos.id:
                            t["exit_price"] = fill["exit_price"]
                            t["exit_reason"] = "CIRCUIT_BREAKER"
                            t["pnl_dollars"] = fill["pnl_dollars"]
                            _accumulate_costs(t, fill)
                            t["pnl_pct"] = fill["pnl_pct"]
                            t["rr_achieved"] = fill["rr_achieved"]
                            t["exit_time"] = str(current_time)
                            t["status"] = "CLOSED"
                            _record_excursion(t, intrabar, current_time)
                            break
                    result.equity_curve.append({
                        "timestamp": str(current_time),
                        "balance": round(account.balance, 2),
                        "pnl": round(fill["pnl_dollars"], 2),
                        "event": "CIRCUIT_BREAKER",
                    })

        # Force-close remaining non-crypto positions at session end (day trade only).
        # Runs AFTER SL/TP check so real fills take priority over synthetic close.
        if not _is_crypto_fn(ticker) and pm.get_open_count() > 0:
            et_time = current_time.astimezone(_ET)
            if _SESSION_END_HOUR <= et_time.hour < _SESSION_END_HOUR + 1:
                for pos in pm.get_open_positions():
                    fill = pm.close_position_manual(pos.id, bar["close"], "SESSION_END")
                    if fill:
                        account.update_balance(fill["pnl_dollars"])
                        for t in result.trades:
                            if t["id"] == pos.id:
                                t["exit_price"] = fill["exit_price"]
                                t["exit_reason"] = "SESSION_END"
                                t["pnl_dollars"] = fill["pnl_dollars"]
                                _accumulate_costs(t, fill)
                                t["pnl_pct"] = fill["pnl_pct"]
                                t["rr_achieved"] = fill["rr_achieved"]
                                t["exit_time"] = str(current_time)
                                t["status"] = "CLOSED"
                                _record_excursion(t, intrabar, current_time)
                                break
                        result.equity_curve.append({
                            "timestamp": str(current_time),
                            "balance": round(account.balance, 2),
                            "pnl": round(fill["pnl_dollars"], 2),
                            "event": "SESSION_END",
                        })

        # Only analyze for new trades on step intervals
        if (i - warmup_bars) % step_bars != 0:
            continue

        result.bars_processed += 1

        # Skip new trades before trade_start (HTF warmup period)
        if trade_start is not None and current_time < trade_start:
            continue

        # Stop new trades after trade_end; exit loop when positions closed
        if trade_end is not None and current_time > trade_end:
            if pm.get_open_count() == 0:
                break
            continue

        # Get point-in-time windowed data
        windowed = get_windowed_data(all_tf, current_time)

        # Skip if insufficient data — entry/setup need more bars than bias/swing
        min_bars = {"bias": 5, "swing": 10, "setup": 20, "entry": 30}
        if any(len(windowed[k]) < min_bars.get(k, 10) for k in windowed):
            continue

        # --- Strategy dispatch ---
        if strategy == "default":
            # Legacy path: confluence scoring + rule-based decision
            try:
                ict_context = analyze_multi_timeframe(
                    windowed, ticker, _cache=_analysis_cache
                )
            except Exception as exc:
                _count(result, f"analysis error: {type(exc).__name__}")
                continue

            score = ict_context.get("confluence_score", 0)

            if score < min_score:
                result.low_confluence_skips += 1
                _count(result, "confluence below threshold")
                continue

            decision = decide_trade(ict_context, min_score)

            if decision["decision"] == "NO_TRADE":
                result.no_trade_decisions += 1
                _count(result, decision.get("reasoning", "no trade"))
                continue
        else:
            # New strategy path: strategies call smc_adapter directly
            strat = get_strategy(strategy)
            try:
                decision = strat.evaluate(
                    windowed, ticker, current_time, _analysis_cache
                )
            except Exception as exc:
                _count(result, f"strategy error: {type(exc).__name__}")
                continue

            if decision is None:
                result.no_trade_decisions += 1
                _count(result, "strategy declined")
                continue
            score = decision.get("confluence_score", 0)

        # Validate trade
        valid, reason = validate_trade(decision, account, pm.get_open_count(), ticker=ticker)
        if not valid:
            _count(result, f"risk check: {reason}")
            continue

        # Open position. Futures trade in whole contracts, so a stop wide enough
        # to price a single contract above the risk budget yields no trade.
        pos = pm.open_position(decision, account, ticker)
        if pos is None:
            result.unaffordable_skips += 1
            continue
        if after_break is not None and after_break[i]:
            result.trades_after_break += 1
        # Override entry_time with backtest timestamp
        pos.entry_time = str(current_time)

        result.trades.append({
            "id": pos.id,
            "ticker": ticker,
            "direction": pos.direction,
            "entry_price": pos.entry_price,
            "stop_loss": pos.stop_loss,
            "take_profit": pos.take_profit,
            "quantity": pos.quantity,
            "risk_amount": pos.risk_amount,
            "entry_time": str(current_time),
            "status": "OPEN",
            "exit_price": None,
            "exit_reason": None,
            "pnl_dollars": None,
            "pnl_pct": None,
            "rr_achieved": None,
            "exit_time": None,
            "setup_type": decision.get("setup_type", ""),
            "confluence_score": score,
            "concepts": decision.get("ict_concepts_used", []),
            "reasoning": decision.get("reasoning", ""),
            "htf_bias": decision.get("htf_bias", ""),
            "risk_reward_ratio": decision.get("risk_reward_ratio", 0),
            "invalidation": decision.get("invalidation", ""),
        })

        # Progress reporting
        if result.bars_processed % progress_every == 0:
            closed = len([t for t in result.trades if t["status"] == "CLOSED"])
            print(
                f"  Bar {result.bars_processed}: "
                f"Balance=${account.balance:,.2f} | "
                f"Trades={len(result.trades)} (closed={closed}) | "
                f"Time={str(current_time)[:10]}"
            )

    # Close any remaining open positions at last price
    last_bar = entry_bars.iloc[-1]
    last_price = last_bar["close"]
    for pos in pm.get_open_positions():
        fill = pm.close_position_manual(pos.id, last_price, "BACKTEST_END")
        if fill:
            account.update_balance(fill["pnl_dollars"])
            for t in result.trades:
                if t["id"] == pos.id:
                    t["exit_price"] = fill["exit_price"]
                    t["exit_reason"] = "BACKTEST_END"
                    t["pnl_dollars"] = fill["pnl_dollars"]
                    _accumulate_costs(t, fill)
                    t["pnl_pct"] = fill["pnl_pct"]
                    t["rr_achieved"] = fill["rr_achieved"]
                    t["exit_time"] = str(last_bar["timestamp"])
                    t["status"] = "CLOSED"
                    _record_excursion(t, intrabar, last_bar["timestamp"])
                    break

    result.equity_curve.append({
        "timestamp": str(last_bar["timestamp"]),
        "balance": round(account.balance, 2),
        "event": "end",
    })

    result.start_time = str(entry_bars.iloc[warmup_bars]["timestamp"])
    result.end_time = str(last_bar["timestamp"])
    result.final_balance = round(account.balance, 2)
    result.max_drawdown_pct = round(account.max_drawdown_pct, 2)
    result.duration_seconds = round(time.time() - t0, 1)

    return result
