"""Walk-forward optimization of confluence threshold.

Splits data into train/test periods, runs backtests at multiple
threshold values, picks the best on train data, validates on test.
"""

from __future__ import annotations

import pandas as pd

from backtest.engine import run_backtest
from config import STARTING_BALANCE


def optimize_threshold(
    df_1m: pd.DataFrame,
    ticker: str = "ES",
    entry_tf: str = "15min",
    thresholds: list[int] | None = None,
    train_pct: float = 0.7,
    starting_balance: float = STARTING_BALANCE,
    trade_start: pd.Timestamp | None = None,
) -> dict:
    """Run walk-forward optimization on the confluence threshold.

    Args:
        df_1m: Full 1-minute OHLCV DataFrame (may include warmup data before trade_start)
        ticker: Ticker symbol
        entry_tf: Entry timeframe
        thresholds: List of thresholds to test (default: [30, 40, 50, 60, 70, 80])
        train_pct: Fraction of TRADABLE data for training (default: 0.7)
        starting_balance: Starting account balance
        trade_start: If set, only split/trade data after this timestamp.
                     Data before this is included in every run for HTF warmup
                     but excluded from the train/test split.

    Returns:
        Dict with train results, test results, and best threshold
    """
    if thresholds is None:
        thresholds = [30, 40, 50, 60, 70, 80]

    # Separate warmup data from tradable data
    if trade_start is not None:
        tradable_mask = df_1m["timestamp"] >= trade_start
        tradable_df = df_1m[tradable_mask]
        warmup_df = df_1m[~tradable_mask]
    else:
        tradable_df = df_1m
        warmup_df = pd.DataFrame()

    # Split TRADABLE data into train/test
    split_idx = int(len(tradable_df) * train_pct)
    train_tradable = tradable_df.iloc[:split_idx]
    test_tradable = tradable_df.iloc[split_idx:]

    # Reconstruct full DataFrames: warmup + tradable portion
    # Each backtest gets all warmup data + its tradable portion
    train_df = pd.concat([warmup_df, train_tradable], ignore_index=True)
    test_df = pd.concat([warmup_df, test_tradable], ignore_index=True)

    # trade_start for train = original trade_start (or start of tradable)
    # trade_start for test = start of test tradable portion
    train_trade_start = trade_start
    test_trade_start = test_tradable["timestamp"].iloc[0] if len(test_tradable) > 0 else None

    train_start = train_tradable["timestamp"].min() if len(train_tradable) > 0 else None
    train_end = train_tradable["timestamp"].max() if len(train_tradable) > 0 else None
    test_start = test_tradable["timestamp"].min() if len(test_tradable) > 0 else None
    test_end = test_tradable["timestamp"].max() if len(test_tradable) > 0 else None

    print(f"  Warmup: {len(warmup_df):,} bars (HTF bias context)")
    print(f"  Train: {str(train_start)[:10]} to {str(train_end)[:10]} ({len(train_tradable):,} tradable bars)")
    print(f"  Test:  {str(test_start)[:10]} to {str(test_end)[:10]} ({len(test_tradable):,} tradable bars)")
    print()

    # Train phase: test each threshold
    train_results = []
    for threshold in thresholds:
        print(f"  Training threshold={threshold}...", end=" ", flush=True)
        result = run_backtest(
            df_1m=train_df,
            starting_balance=starting_balance,
            min_score=threshold,
            ticker=ticker,
            entry_tf=entry_tf,
            trade_start=train_trade_start,
        )
        trades = len(result.trades)
        closed = [t for t in result.trades if t["status"] == "CLOSED"]
        wins = [t for t in closed if (t.get("pnl_dollars") or 0) > 0]
        pnl = result.final_balance - result.starting_balance
        win_rate = len(wins) / len(closed) * 100 if closed else 0
        pf = _profit_factor(closed)

        train_results.append({
            "threshold": threshold,
            "trades": trades,
            "win_rate": round(win_rate, 1),
            "pnl": round(pnl, 2),
            "profit_factor": round(pf, 2),
            "max_drawdown": _max_drawdown(result),
        })
        print(f"{trades} trades, {win_rate:.0f}% WR, PF={pf:.2f}, P&L=${pnl:,.0f}")

    # Pick best by profit factor (with minimum trade count)
    valid = [r for r in train_results if r["trades"] >= 5]
    if not valid:
        valid = train_results
    best = max(valid, key=lambda r: r["profit_factor"])
    best_threshold = best["threshold"]

    print(f"\n  Best threshold: {best_threshold} (PF={best['profit_factor']}, {best['trades']} trades)")

    # Test phase: validate on unseen data
    print(f"\n  Validating on test data with threshold={best_threshold}...")
    test_result = run_backtest(
        df_1m=test_df,
        starting_balance=starting_balance,
        min_score=best_threshold,
        ticker=ticker,
        entry_tf=entry_tf,
        trade_start=test_trade_start,
    )
    test_closed = [t for t in test_result.trades if t["status"] == "CLOSED"]
    test_wins = [t for t in test_closed if (t.get("pnl_dollars") or 0) > 0]
    test_pnl = test_result.final_balance - test_result.starting_balance
    test_wr = len(test_wins) / len(test_closed) * 100 if test_closed else 0
    test_pf = _profit_factor(test_closed)

    test_summary = {
        "threshold": best_threshold,
        "trades": len(test_result.trades),
        "win_rate": round(test_wr, 1),
        "pnl": round(test_pnl, 2),
        "profit_factor": round(test_pf, 2),
        "max_drawdown": _max_drawdown(test_result),
    }

    return {
        "best_threshold": best_threshold,
        "train_results": train_results,
        "test_result": test_summary,
    }


def _profit_factor(closed_trades: list) -> float:
    """Calculate profit factor from closed trades."""
    gross_profit = sum(t.get("pnl_dollars", 0) for t in closed_trades if (t.get("pnl_dollars") or 0) > 0)
    gross_loss = abs(sum(t.get("pnl_dollars", 0) for t in closed_trades if (t.get("pnl_dollars") or 0) < 0))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0
    return gross_profit / gross_loss


def _max_drawdown(result) -> float:
    """Calculate max drawdown percentage from equity curve."""
    peak = result.starting_balance
    max_dd = 0
    balance = result.starting_balance
    for point in result.equity_curve:
        balance = point.get("balance", balance)
        peak = max(peak, balance)
        if peak > 0:
            dd = (peak - balance) / peak * 100
            max_dd = max(max_dd, dd)
    return round(max_dd, 1)
