"""Analytics and reporting for backtest results.

Generates statistics, equity curves, and trade summaries from BacktestResult.
Uses vectorbt for advanced analytics when available, falls back to pandas.
"""

import json
from pathlib import Path

import pandas as pd

from backtest.engine import BacktestResult


def calc_stats(result: BacktestResult) -> dict:
    """Calculate comprehensive trading statistics from backtest results.

    Returns:
        Dict with all performance metrics
    """
    trades = result.trades
    closed = [t for t in trades if t.get("status") == "CLOSED"]

    if not closed:
        return {
            "total_trades": 0,
            "bars_processed": result.bars_processed,
            "low_confluence_skips": result.low_confluence_skips,
            "no_trade_decisions": result.no_trade_decisions,
            "duration_seconds": result.duration_seconds,
        }

    wins = [t for t in closed if (t.get("pnl_dollars") or 0) > 0]
    losses = [t for t in closed if (t.get("pnl_dollars") or 0) <= 0]

    total_profit = sum(t["pnl_dollars"] for t in wins)
    total_loss = abs(sum(t["pnl_dollars"] for t in losses))

    # Equity curve analysis
    eq = pd.DataFrame(result.equity_curve)
    if "balance" in eq.columns and len(eq) > 1:
        peak = eq["balance"].expanding().max()
        drawdown = (eq["balance"] - peak) / peak * 100
        max_drawdown = abs(drawdown.min())
    else:
        max_drawdown = 0

    # R:R distribution
    rrs = [t["rr_achieved"] for t in closed if t.get("rr_achieved") is not None]

    # Win/loss streaks
    outcomes = [1 if (t.get("pnl_dollars") or 0) > 0 else 0 for t in closed]
    max_win_streak = _max_streak(outcomes, 1)
    max_loss_streak = _max_streak(outcomes, 0)

    # Monthly returns
    monthly = _calc_monthly_returns(closed, result.starting_balance)

    # Setup type breakdown
    setup_stats = _calc_setup_stats(closed)

    # Trade duration analysis
    durations = _calc_trade_durations(closed)

    net_pnl = total_profit - total_loss
    return_pct = (result.final_balance - result.starting_balance) / result.starting_balance * 100

    return {
        "starting_balance": result.starting_balance,
        "final_balance": result.final_balance,
        "net_pnl": round(net_pnl, 2),
        "return_pct": round(return_pct, 2),
        "total_trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(closed) * 100, 1),
        "profit_factor": round(total_profit / total_loss, 2) if total_loss > 0 else float("inf"),
        "total_profit": round(total_profit, 2),
        "total_loss": round(total_loss, 2),
        "avg_win": round(total_profit / len(wins), 2) if wins else 0,
        "avg_loss": round(total_loss / len(losses), 2) if losses else 0,
        "best_trade": round(max(t["pnl_dollars"] for t in closed), 2),
        "worst_trade": round(min(t["pnl_dollars"] for t in closed), 2),
        "avg_rr": round(sum(rrs) / len(rrs), 2) if rrs else 0,
        "max_drawdown_pct": round(max_drawdown, 2),
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "monthly_returns": monthly,
        "setup_stats": setup_stats,
        "avg_trade_duration": durations.get("avg", "N/A"),
        "bars_processed": result.bars_processed,
        "low_confluence_skips": result.low_confluence_skips,
        "no_trade_decisions": result.no_trade_decisions,
        "backtest_duration_seconds": result.duration_seconds,
        "period": f"{result.start_time[:10]} to {result.end_time[:10]}",
        "parameters": result.parameters,
    }


def print_report(result: BacktestResult):
    """Print a formatted backtest report to console."""
    stats = calc_stats(result)

    if stats["total_trades"] == 0:
        print("\n  No trades were executed during the backtest.")
        print(f"  Bars processed: {stats['bars_processed']}")
        print(f"  Low confluence skips: {stats['low_confluence_skips']}")
        print(f"  No-trade decisions: {stats['no_trade_decisions']}")
        return

    print(f"\n{'='*60}")
    print(f"  BACKTEST RESULTS")
    print(f"{'='*60}")
    print(f"  Period:           {stats['period']}")
    print(f"  Duration:         {stats['backtest_duration_seconds']:.1f}s")
    print(f"  Parameters:       score>={stats['parameters'].get('min_score', '?')}")
    print(f"")
    print(f"  --- Performance ---")
    print(f"  Starting Balance: ${stats['starting_balance']:>12,.2f}")
    print(f"  Final Balance:    ${stats['final_balance']:>12,.2f}")
    print(f"  Net P&L:          ${stats['net_pnl']:>12,.2f} ({stats['return_pct']:+.1f}%)")
    print(f"  Max Drawdown:     {stats['max_drawdown_pct']:.1f}%")
    print(f"  Profit Factor:    {stats['profit_factor']}")
    print(f"")
    print(f"  --- Trades ---")
    print(f"  Total Trades:     {stats['total_trades']}")
    print(f"  Win Rate:         {stats['win_rate']}%")
    print(f"  Wins / Losses:    {stats['wins']} / {stats['losses']}")
    print(f"  Avg Win:          ${stats['avg_win']:,.2f}")
    print(f"  Avg Loss:         ${stats['avg_loss']:,.2f}")
    print(f"  Best Trade:       ${stats['best_trade']:,.2f}")
    print(f"  Worst Trade:      ${stats['worst_trade']:,.2f}")
    print(f"  Avg R:R:          {stats['avg_rr']}")
    print(f"  Max Win Streak:   {stats['max_win_streak']}")
    print(f"  Max Loss Streak:  {stats['max_loss_streak']}")

    # Setup type breakdown
    if stats.get("setup_stats"):
        print(f"\n  --- Setup Types ---")
        for stype, sdata in stats["setup_stats"].items():
            print(f"  {stype:20s} {sdata['count']:>3d} trades, {sdata['win_rate']:.0f}% WR, ${sdata['net_pnl']:>10,.2f}")

    # Monthly returns
    if stats.get("monthly_returns"):
        print(f"\n  --- Monthly Returns ---")
        for month, ret in stats["monthly_returns"].items():
            print(f"  {month}:  ${ret:>10,.2f}")

    print(f"\n  --- Engine Stats ---")
    print(f"  Bars Processed:   {stats['bars_processed']}")
    print(f"  Low Confluence:   {stats['low_confluence_skips']}")
    print(f"  No-Trade Rules:   {stats['no_trade_decisions']}")
    print(f"{'='*60}\n")


def save_results(result: BacktestResult, filepath: str):
    """Save backtest results to JSON file."""
    stats = calc_stats(result)
    output = {
        "stats": stats,
        "trades": result.trades,
        "equity_curve": result.equity_curve,
    }
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, indent=2, default=str))
    print(f"  Results saved to {filepath}")


def print_trades(result: BacktestResult, limit: int = 20):
    """Print recent trades in a compact table."""
    trades = [t for t in result.trades if t.get("status") == "CLOSED"]
    if not trades:
        print("  No closed trades.")
        return

    print(f"\n  --- Last {min(limit, len(trades))} Trades ---")
    print(f"  {'Dir':5s} {'Entry':>10s} {'Exit':>10s} {'P&L':>10s} {'R:R':>5s} {'Setup':15s} {'Score':>5s}")
    print(f"  {'-'*65}")

    for t in trades[-limit:]:
        direction = t.get("direction", "?")
        entry = t.get("entry_price", 0)
        exit_p = t.get("exit_price", 0)
        pnl = t.get("pnl_dollars", 0)
        rr = t.get("rr_achieved", 0)
        setup = t.get("setup_type", "?")[:15]
        score = t.get("confluence_score", 0)
        marker = "W" if pnl > 0 else "L"
        print(f"  {direction:5s} {entry:>10.2f} {exit_p:>10.2f} {pnl:>+10.2f} {rr:>5.1f} {setup:15s} {score:>5d} {marker}")


def generate_equity_csv(result: BacktestResult, filepath: str):
    """Export equity curve to CSV for external charting."""
    eq = pd.DataFrame(result.equity_curve)
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    eq.to_csv(path, index=False)
    print(f"  Equity curve saved to {filepath}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _max_streak(outcomes: list, target: int) -> int:
    """Find the longest consecutive streak of target value."""
    max_s = 0
    current = 0
    for o in outcomes:
        if o == target:
            current += 1
            max_s = max(max_s, current)
        else:
            current = 0
    return max_s


def _calc_monthly_returns(closed_trades: list, starting_balance: float) -> dict:
    """Calculate net P&L per month."""
    monthly = {}
    for t in closed_trades:
        exit_time = t.get("exit_time", "")
        if not exit_time:
            continue
        month_key = exit_time[:7]  # "YYYY-MM"
        monthly[month_key] = monthly.get(month_key, 0) + (t.get("pnl_dollars") or 0)

    return {k: round(v, 2) for k, v in sorted(monthly.items())}


def _calc_setup_stats(closed_trades: list) -> dict:
    """Calculate stats per setup type."""
    by_type = {}
    for t in closed_trades:
        stype = t.get("setup_type", "Unknown") or "Unknown"
        if stype not in by_type:
            by_type[stype] = {"trades": [], "wins": 0, "losses": 0, "net_pnl": 0}
        by_type[stype]["trades"].append(t)
        pnl = t.get("pnl_dollars", 0)
        by_type[stype]["net_pnl"] += pnl
        if pnl > 0:
            by_type[stype]["wins"] += 1
        else:
            by_type[stype]["losses"] += 1

    result = {}
    for stype, data in by_type.items():
        total = data["wins"] + data["losses"]
        result[stype] = {
            "count": total,
            "wins": data["wins"],
            "losses": data["losses"],
            "win_rate": data["wins"] / total * 100 if total else 0,
            "net_pnl": round(data["net_pnl"], 2),
        }
    return result


def _calc_trade_durations(closed_trades: list) -> dict:
    """Calculate average trade duration."""
    durations = []
    for t in closed_trades:
        entry = t.get("entry_time")
        exit_t = t.get("exit_time")
        if entry and exit_t:
            try:
                e = pd.Timestamp(entry)
                x = pd.Timestamp(exit_t)
                durations.append(x - e)
            except Exception:
                pass

    if not durations:
        return {"avg": "N/A"}

    avg = sum(durations, pd.Timedelta(0)) / len(durations)
    return {"avg": str(avg)}
