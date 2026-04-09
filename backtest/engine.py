"""Walk-forward backtesting engine for ICT strategies.

Iterates through entry-timeframe bars, runs the full ICT detection pipeline
at each step with point-in-time data (no look-ahead bias), and simulates
trades using the existing position/risk management modules.
"""

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd

from zoneinfo import ZoneInfo

from backtest.rules import decide_trade
from config import BACKTEST_SMC_SWING_LENGTH, MIN_CONFLUENCE_SCORE, STARTING_BALANCE
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
    bars_processed: int = 0
    start_time: str = ""
    end_time: str = ""
    duration_seconds: float = 0
    starting_balance: float = 0
    final_balance: float = 0
    parameters: dict = field(default_factory=dict)


# Default warmup and step values per entry timeframe
_ENTRY_TF_DEFAULTS = {
    "1min":  {"warmup": 1000, "step": 15},   # analyze every 15 min
    "5min":  {"warmup": 500,  "step": 3},    # analyze every 15 min
    "15min": {"warmup": 200,  "step": 4},    # analyze every hour
    "30min": {"warmup": 100,  "step": 2},    # analyze every hour
    "1h":    {"warmup": 50,   "step": 1},    # analyze every hour
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

    # Use smaller swing_length for backtesting (less warmup needed).
    # Wrapped in try/finally to guarantee restoration even on exceptions.
    set_swing_length_override(BACKTEST_SMC_SWING_LENGTH)
    try:
        return _run_backtest_inner(
            df_1m, starting_balance, min_score, ticker,
            entry_tf, step_bars, warmup_bars, progress_every, t0,
        )
    finally:
        set_swing_length_override(None)


def _run_backtest_inner(
    df_1m, starting_balance, min_score, ticker,
    entry_tf, step_bars, warmup_bars, progress_every, t0,
) -> BacktestResult:
    """Inner backtest loop, separated so run_backtest can wrap in try/finally."""
    # Build all timeframes from 1m data
    print(f"  Resampling 1m data to all timeframes (entry={entry_tf})...")
    all_tf = build_multi_timeframe(df_1m, entry_tf=entry_tf)
    entry_bars = all_tf["entry"]

    print(f"  Entry bars: {len(entry_bars)}, Warmup: {warmup_bars}, Step: {step_bars}")
    print(f"  Bars to process: ~{(len(entry_bars) - warmup_bars) // step_bars}")

    # Initialize account and position manager
    account = Account(starting_balance=starting_balance)
    pm = PositionManager()

    result = BacktestResult(
        starting_balance=starting_balance,
        parameters={
            "min_score": min_score,
            "step_bars": step_bars,
            "warmup_bars": warmup_bars,
            "ticker": ticker,
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
            # Find the original trade in results and update it
            for t in result.trades:
                if t["id"] == fill["position_id"]:
                    t["exit_price"] = fill["exit_price"]
                    t["exit_reason"] = fill["exit_reason"]
                    t["pnl_dollars"] = fill["pnl_dollars"]
                    t["pnl_pct"] = fill["pnl_pct"]
                    t["rr_achieved"] = fill["rr_achieved"]
                    t["exit_time"] = str(current_time)
                    t["status"] = "CLOSED"
                    break

            result.equity_curve.append({
                "timestamp": str(current_time),
                "balance": round(account.balance, 2),
                "pnl": round(pnl, 2),
                "event": fill["exit_reason"],
            })

        # Force-close remaining non-crypto positions at session end (day trade only).
        # Runs AFTER SL/TP check so real fills take priority over synthetic close.
        if not _is_crypto_fn(ticker) and pm.get_open_count() > 0:
            et_time = current_time.astimezone(_ET)
            if et_time.hour >= _SESSION_END_HOUR:
                for pos in pm.get_open_positions():
                    fill = pm.close_position_manual(pos.id, bar["close"])
                    if fill:
                        account.update_balance(fill["pnl_dollars"])
                        for t in result.trades:
                            if t["id"] == pos.id:
                                t["exit_price"] = fill["exit_price"]
                                t["exit_reason"] = "SESSION_END"
                                t["pnl_dollars"] = fill["pnl_dollars"]
                                t["pnl_pct"] = fill["pnl_pct"]
                                t["rr_achieved"] = fill["rr_achieved"]
                                t["exit_time"] = str(current_time)
                                t["status"] = "CLOSED"
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

        # Get point-in-time windowed data
        windowed = get_windowed_data(all_tf, current_time)

        # Skip if insufficient data — entry/setup need more bars than bias/swing
        min_bars = {"bias": 5, "swing": 10, "setup": 20, "entry": 30}
        if any(len(windowed[k]) < min_bars.get(k, 10) for k in windowed):
            continue

        # Run ICT analysis with HTF caching — only recompute a timeframe
        # when its latest bar changes (daily changes once/day, 4H once/4h, etc.)
        try:
            ict_context = analyze_multi_timeframe(
                windowed, ticker, _cache=_analysis_cache
            )
        except Exception:
            continue

        score = ict_context.get("confluence_score", 0)

        # Check confluence threshold
        if score < min_score:
            result.low_confluence_skips += 1
            continue

        # Rule-based decision
        decision = decide_trade(ict_context, min_score)

        if decision["decision"] == "NO_TRADE":
            result.no_trade_decisions += 1
            continue

        # Validate trade
        valid, reason = validate_trade(decision, account, pm.get_open_count())
        if not valid:
            continue

        # Open position
        pos = pm.open_position(decision, account, ticker)
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
        fill = pm.close_position_manual(pos.id, last_price)
        if fill:
            account.update_balance(fill["pnl_dollars"])
            for t in result.trades:
                if t["id"] == pos.id:
                    t["exit_price"] = fill["exit_price"]
                    t["exit_reason"] = "BACKTEST_END"
                    t["pnl_dollars"] = fill["pnl_dollars"]
                    t["pnl_pct"] = fill["pnl_pct"]
                    t["rr_achieved"] = fill["rr_achieved"]
                    t["exit_time"] = str(last_bar["timestamp"])
                    t["status"] = "CLOSED"
                    break

    result.equity_curve.append({
        "timestamp": str(last_bar["timestamp"]),
        "balance": round(account.balance, 2),
        "event": "end",
    })

    result.start_time = str(entry_bars.iloc[warmup_bars]["timestamp"])
    result.end_time = str(last_bar["timestamp"])
    result.final_balance = round(account.balance, 2)
    result.duration_seconds = round(time.time() - t0, 1)

    return result
