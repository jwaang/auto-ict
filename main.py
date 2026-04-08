"""ICT Paper Trading Simulator — CLI entry point.

Usage:
    python main.py analyze AAPL          # Run ICT analysis on AAPL
    python main.py analyze BTC-USD       # Analyze Bitcoin
    python main.py check-positions       # Check open positions for SL/TP fills
    python main.py stats                 # Show trading statistics
    python main.py journal              # Show recent journal entries
"""

import argparse
import json
import sys

from config import MIN_CONFLUENCE_SCORE, STARTING_BALANCE
from data.yahoo import fetch_multi_timeframe
from ict.confluence import analyze_multi_timeframe
from journal.logger import get_open_trade_count
from trading.account import Account
from trading.positions import PositionManager
from trading.risk import validate_trade


def cmd_analyze(ticker: str, balance: float | None = None):
    """Run full ICT analysis → AI decision → paper trade."""
    account = Account(starting_balance=balance or STARTING_BALANCE)

    # Load existing state from journal if available
    try:
        from journal.logger import load_journal
        journal = load_journal()
        meta = journal.get("metadata", {})
        if meta.get("current_balance"):
            account.balance = meta["current_balance"]
            account.peak_balance = max(account.balance, account.starting_balance)
    except Exception:
        pass

    print(f"\n{'='*60}")
    print(f"  ICT Paper Trading Simulator")
    print(f"  Analyzing: {ticker}")
    print(f"  Account: ${account.balance:,.2f}")
    print(f"{'='*60}\n")

    # Step 1: Fetch OHLC data
    print("[1/5] Fetching OHLC data (3 timeframes)...")
    try:
        dataframes = fetch_multi_timeframe(ticker)
        for label, df in dataframes.items():
            print(f"      {label}: {len(df)} candles")
    except Exception as e:
        print(f"  ERROR: Failed to fetch data: {e}")
        return

    # Step 2: Run ICT detection
    print("[2/5] Running ICT detection engine...")
    ict_context = analyze_multi_timeframe(dataframes, ticker)

    analyses = ict_context.get("analyses", {})
    for tf_label, tf_data in analyses.items():
        bias = tf_data.get("bias", "?")
        fvgs = len(tf_data.get("unfilled_fvgs", []))
        obs = len(tf_data.get("unmitigated_obs", []))
        disps = len(tf_data.get("displacements", []))
        print(f"      {tf_label}: bias={bias}, FVGs={fvgs}, OBs={obs}, displacements={disps}")

    score = ict_context.get("confluence_score", 0)
    print(f"\n      Confluence Score: {score}/100 (minimum: {MIN_CONFLUENCE_SCORE})")

    # Step 3: Check confluence threshold
    if score < MIN_CONFLUENCE_SCORE:
        print(f"\n[3/5] Score below threshold — AI not consulted.")
        print(f"      Logging as low-confluence no-trade decision.")
        from journal.logger import log_low_confluence
        log_low_confluence(ticker, score, ict_context)
        _print_ict_summary(ict_context)
        return

    # Step 4: AI Analysis
    print(f"[3/5] Sending to Claude API for ICT analysis...")
    try:
        from ai.analyst import analyze
        account_state = account.snapshot()
        account_state["open_position_count"] = get_open_trade_count()
        decision = analyze(ict_context, account_state)
    except Exception as e:
        print(f"  ERROR: AI analysis failed: {e}")
        return

    print(f"\n      Decision: {decision.get('decision', 'UNKNOWN')}")
    print(f"      Confidence: {decision.get('confidence', '?')}/10")
    print(f"      Setup: {decision.get('setup_type', '?')}")
    print(f"      HTF Bias: {decision.get('htf_bias', '?')}")

    if decision.get("entry_price"):
        print(f"\n      Entry:  ${decision['entry_price']:.2f}")
        print(f"      SL:     ${decision['stop_loss']:.2f}")
        print(f"      TP:     ${decision['take_profit']:.2f}")
        print(f"      R:R:    {decision.get('risk_reward_ratio', '?')}")

    print(f"\n      Reasoning: {decision.get('reasoning', 'N/A')}")
    print(f"      Concepts: {', '.join(decision.get('ict_concepts_used', []))}")
    print(f"      Invalidation: {decision.get('invalidation', 'N/A')}")

    # Step 5: Execute paper trade
    from journal import logger

    decision_type = decision.get("decision", "")

    if decision_type in ("LONG", "SHORT"):
        print(f"\n[4/5] Validating risk management...")
        valid, reason = validate_trade(decision, account, get_open_trade_count())

        if valid:
            print(f"      VALID — Opening paper trade")
            pm = PositionManager()
            pos = pm.open_position(decision, account, ticker)
            trade_id = logger.log_trade(
                ticker=ticker,
                position=vars(pos),
                ai_decision=decision,
                ict_context=ict_context,
                account_before=account.balance,
                account_after=account.balance,
            )
            print(f"      Position ID: {pos.id}")
            print(f"      Quantity: {pos.quantity}")
            print(f"      Risk: ${pos.risk_amount:.2f}")
            print(f"      Trade logged: {trade_id}")
        else:
            print(f"      REJECTED: {reason}")
            logger.log_no_trade(ticker, decision, ict_context, score)

    elif decision_type in ("CONDITIONAL_LONG", "CONDITIONAL_SHORT"):
        entry_zones = decision.get("entry_zones", [])
        print(f"\n[4/5] CONDITIONAL — {len(entry_zones)} entry zone(s) set")
        for i, zone in enumerate(entry_zones):
            priority = zone.get("priority", "?")
            z_type = zone.get("zone_type", "?")
            z_low = zone.get("zone_low", 0)
            z_high = zone.get("zone_high", 0)
            sl = zone.get("stop_loss", 0)
            tp1 = zone.get("take_profit_1", 0)
            rr = zone.get("risk_reward", "?")
            confirm = zone.get("confirmation_needed", "?")
            print(f"      Zone {i+1} (P{priority}): {z_type} ${z_low:,.2f}-${z_high:,.2f}")
            print(f"        SL=${sl:,.2f} TP=${tp1:,.2f} R:R={rr}")
            print(f"        Confirmation: {confirm}")
            print(f"        Reason: {zone.get('reasoning', 'N/A')}")

        cond_id = logger.log_conditional_entry(ticker, decision, ict_context, score)
        print(f"\n      Conditional entry logged: {cond_id}")
        print(f"      Monitor will watch for price to enter zones and confirm LTF signal.")

    else:
        print(f"\n[4/5] AI decided NO_TRADE — logging decision")
        logger.log_no_trade(ticker, decision, ict_context, score)

    print(f"\n[5/5] Done.")


def cmd_check_positions(ticker: str | None = None):
    """Check open positions against latest price data for SL/TP fills."""
    from data.yahoo import fetch_ohlc
    from journal.logger import load_journal

    journal = load_journal()
    open_trades = [t for t in journal.get("trades", []) if t.get("status") == "OPEN"]

    if not open_trades:
        print("No open positions to check.")
        return

    print(f"\nChecking {len(open_trades)} open position(s)...\n")

    for trade in open_trades:
        t_ticker = trade["ticker"]
        if ticker and t_ticker != ticker:
            continue

        try:
            df = fetch_ohlc(t_ticker, "15m", "1d")
            latest = df.iloc[-1]
            high = latest["high"]
            low = latest["low"]
            current = latest["close"]

            entry = trade["entry_price"]
            sl = trade["stop_loss"]
            tp = trade["take_profit"]
            direction = trade["direction"]

            print(f"  {t_ticker} {direction} @ ${entry:.2f}")
            print(f"    Current: ${current:.2f} | SL: ${sl:.2f} | TP: ${tp:.2f}")

            hit = None
            if direction == "LONG":
                if low <= sl:
                    hit = ("SL_HIT", sl)
                elif high >= tp:
                    hit = ("TP_HIT", tp)
            else:
                if high >= sl:
                    hit = ("SL_HIT", sl)
                elif low <= tp:
                    hit = ("TP_HIT", tp)

            if hit:
                reason, exit_price = hit
                if direction == "LONG":
                    pnl = (exit_price - entry) * trade.get("quantity", 0)
                else:
                    pnl = (entry - exit_price) * trade.get("quantity", 0)
                print(f"    >>> {reason} at ${exit_price:.2f} | P&L: ${pnl:.2f}")

                from journal.logger import update_trade_close
                balance_after = trade.get("account_balance_before", 100000) + pnl
                update_trade_close(trade["id"], {
                    "exit_price": exit_price,
                    "exit_reason": reason,
                    "pnl_dollars": round(pnl, 2),
                    "pnl_pct": round(pnl / (entry * trade.get("quantity", 1)) * 100, 2),
                }, balance_after)
            else:
                unrealized = 0
                if direction == "LONG":
                    unrealized = (current - entry) * trade.get("quantity", 0)
                else:
                    unrealized = (entry - current) * trade.get("quantity", 0)
                print(f"    Still open | Unrealized P&L: ${unrealized:.2f}")
        except Exception as e:
            print(f"    Error checking {t_ticker}: {e}")
        print()


def cmd_stats():
    """Display trading statistics."""
    from journal.logger import get_stats

    stats = get_stats()
    print(f"\n{'='*40}")
    print(f"  ICT Paper Trading Statistics")
    print(f"{'='*40}")

    if stats["total_trades"] == 0:
        print(f"  No closed trades yet.")
        print(f"  Open trades: {stats.get('open_trades', 0)}")
        print(f"  No-trade decisions: {stats.get('no_trade_decisions', 0)}")
        return

    print(f"  Total Trades:     {stats['total_trades']}")
    print(f"  Wins:             {stats['wins']}")
    print(f"  Losses:           {stats['losses']}")
    print(f"  Win Rate:         {stats['win_rate']}%")
    print(f"  Net P&L:          ${stats['net_pnl']:,.2f}")
    print(f"  Profit Factor:    {stats['profit_factor']}")
    print(f"  Avg R:R:          {stats['avg_rr']}")
    print(f"  Best Trade:       ${stats['best_trade']:,.2f}")
    print(f"  Worst Trade:      ${stats['worst_trade']:,.2f}")
    print(f"  Open Trades:      {stats['open_trades']}")
    print(f"  No-Trade Calls:   {stats['no_trade_decisions']}")
    print()


def cmd_journal(limit: int = 10):
    """Show recent journal entries."""
    from journal.logger import load_journal

    data = load_journal()
    trades = data.get("trades", [])
    no_trades = data.get("no_trade_decisions", [])

    print(f"\n--- Recent Trades (last {limit}) ---")
    for t in trades[-limit:]:
        status = t.get("status", "?")
        pnl = t.get("pnl_dollars")
        pnl_str = f"${pnl:+.2f}" if pnl is not None else "open"
        print(f"  [{status}] {t['ticker']} {t['direction']} @ ${t['entry_price']:.2f} → {pnl_str}")
        print(f"         {t.get('ai_decision', {}).get('setup_type', '?')}")

    print(f"\n--- Recent No-Trade Decisions (last {min(limit, 5)}) ---")
    for nt in no_trades[-min(limit, 5):]:
        score = nt.get("confluence_score", "?")
        print(f"  {nt['ticker']} (score: {score}) — {nt.get('reasoning', '?')[:80]}...")
    print()


def _print_ict_summary(ctx: dict):
    """Print a brief ICT analysis summary."""
    print(f"\n--- ICT Summary ---")
    print(f"  HTF Bias: {ctx.get('htf_bias', '?')}")
    for tf, data in ctx.get("analyses", {}).items():
        unfilled = data.get("unfilled_fvgs", [])
        obs = data.get("unmitigated_obs", [])
        print(f"  {tf}:")
        if unfilled:
            for f in unfilled[-3:]:
                print(f"    FVG {f['type']}: {f['bottom']:.2f} - {f['top']:.2f}")
        if obs:
            for ob in obs[-3:]:
                print(f"    OB  {ob['type']}: {ob['low']:.2f} - {ob['high']:.2f}")
    confs = ctx.get("confluences", [])
    if confs:
        print(f"  Confluences:")
        for c in confs:
            print(f"    {c['type']} ({c.get('direction', '?')})")
    print()


def cmd_backtest(
    data_path: str,
    balance: float | None = None,
    min_score: int | None = None,
    start: str | None = None,
    end: str | None = None,
    step: int = 4,
    save_path: str | None = None,
    show_trades: int = 20,
):
    """Run a walk-forward backtest on historical data."""
    from backtest.engine import run_backtest
    from backtest.report import print_report, print_trades, save_results, generate_equity_csv
    from data.historical import load_continuous_contract

    balance = balance or STARTING_BALANCE
    min_score = min_score if min_score is not None else MIN_CONFLUENCE_SCORE

    print(f"\n{'='*60}")
    print(f"  ICT Backtesting Engine")
    print(f"  Data: {data_path}")
    print(f"  Balance: ${balance:,.2f}")
    print(f"  Min Score: {min_score}")
    print(f"{'='*60}\n")

    # Load data
    print("[1/3] Loading historical data...")
    try:
        df_1m = load_continuous_contract(data_path, start=start, end=end)
        print(f"      Loaded {len(df_1m):,} bars ({df_1m['timestamp'].min()} to {df_1m['timestamp'].max()})")
    except Exception as e:
        print(f"  ERROR: Failed to load data: {e}")
        return

    # Run backtest
    print("[2/3] Running backtest...")
    result = run_backtest(
        df_1m=df_1m,
        starting_balance=balance,
        min_score=min_score,
        ticker="ES",
        step_bars=step,
    )

    # Report
    print("[3/3] Generating report...")
    print_report(result)
    if show_trades:
        print_trades(result, limit=show_trades)

    # Save results
    if save_path:
        save_results(result, save_path)
        eq_path = save_path.replace(".json", "_equity.csv")
        generate_equity_csv(result, eq_path)
    else:
        # Default save location
        from config import PROJECT_ROOT
        default_path = str(PROJECT_ROOT / "logs" / "backtest_results.json")
        save_results(result, default_path)


def main():
    parser = argparse.ArgumentParser(description="ICT Paper Trading Simulator")
    sub = parser.add_subparsers(dest="command")

    p_analyze = sub.add_parser("analyze", help="Run ICT analysis on a ticker")
    p_analyze.add_argument("ticker", help="Ticker symbol (e.g. AAPL, BTC-USD)")
    p_analyze.add_argument("--balance", type=float, help="Override starting balance")

    p_check = sub.add_parser("check-positions", help="Check open positions for fills")
    p_check.add_argument("--ticker", help="Filter by ticker")

    sub.add_parser("stats", help="Show trading statistics")

    p_journal = sub.add_parser("journal", help="Show recent journal entries")
    p_journal.add_argument("--limit", type=int, default=10, help="Number of entries")

    p_bt = sub.add_parser("backtest", help="Run backtest on historical data")
    p_bt.add_argument("data", help="Path to OHLCV CSV file")
    p_bt.add_argument("--balance", type=float, help="Starting balance (default: 100000)")
    p_bt.add_argument("--min-score", type=int, help="Min confluence score (default: 60)")
    p_bt.add_argument("--start", help="Start date (YYYY-MM-DD)")
    p_bt.add_argument("--end", help="End date (YYYY-MM-DD)")
    p_bt.add_argument("--step", type=int, default=4, help="Analyze every Nth entry bar (default: 4)")
    p_bt.add_argument("--save", help="Path to save results JSON")
    p_bt.add_argument("--trades", type=int, default=20, help="Number of recent trades to show")

    args = parser.parse_args()

    if args.command == "analyze":
        cmd_analyze(args.ticker, args.balance)
    elif args.command == "check-positions":
        cmd_check_positions(args.ticker if hasattr(args, "ticker") else None)
    elif args.command == "stats":
        cmd_stats()
    elif args.command == "journal":
        cmd_journal(args.limit)
    elif args.command == "backtest":
        cmd_backtest(
            data_path=args.data,
            balance=args.balance,
            min_score=args.min_score,
            start=args.start,
            end=args.end,
            step=args.step,
            save_path=args.save,
            show_trades=args.trades,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
