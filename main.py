"""ICT Paper Trading Simulator — CLI entry point.

Usage:
    python main.py analyze MES           # Run ICT analysis on MES via IBKR
    python main.py check-positions       # Check open IBKR positions
    python main.py stats                 # Show trading statistics
    python main.py journal              # Show recent journal entries
"""

import argparse
import json
import sys

import pandas as pd

from config import (
    MIN_CONFLUENCE_SCORE,
    MES_POINT_VALUE,
    STARTING_BALANCE,
    USE_AI_ANALYSIS,
    is_futures,
)
from ict.confluence import analyze_multi_timeframe
from journal.logger import get_open_trade_count
from trading.account import Account
from trading.risk import validate_trade


def cmd_analyze(ticker: str, balance: float | None = None):
    """Run full ICT analysis → trade decision → IBKR bracket order."""
    from broker.ibkr import IBKRBroker

    broker = IBKRBroker()

    # Connect to IBKR
    print(f"\n{'='*60}")
    print(f"  ICT Paper Trading Simulator (IBKR)")
    print(f"  Analyzing: {ticker}")
    print(f"{'='*60}\n")

    print("[1/5] Connecting to IBKR...")
    try:
        broker.connect()
    except ConnectionError as e:
        print(f"  ERROR: {e}")
        return

    # Get account balance from IBKR
    try:
        acct = broker.get_account_summary()
        ibkr_balance = acct.get("balance", balance or STARTING_BALANCE)
    except Exception:
        ibkr_balance = balance or STARTING_BALANCE

    account = Account(starting_balance=ibkr_balance, balance=ibkr_balance)
    print(f"  Account: ${account.balance:,.2f}")

    # Step 1: Fetch OHLC data from IBKR
    print("[2/5] Fetching OHLC data from IBKR (4 timeframes)...")
    try:
        contract = broker.get_mes_contract()
        dataframes = broker.fetch_multi_timeframe(contract)
        for label, df in dataframes.items():
            print(f"      {label}: {len(df)} candles")
    except Exception as e:
        print(f"  ERROR: Failed to fetch data: {e}")
        broker.disconnect()
        return

    # Step 2: Run ICT detection
    print("[3/5] Running ICT detection engine...")
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

    # Step 3: Pre-flight checks
    from config import ENFORCE_KILL_ZONES
    from ict.killzones import is_in_dead_zone, is_in_killzone, is_crypto
    entry_data = ict_context.get("analyses", {}).get("entry", {})
    current_ts_str = entry_data.get("current_timestamp")

    # Kill zone / dead zone checks (respects global ENFORCE_KILL_ZONES flag)
    if ENFORCE_KILL_ZONES and not is_crypto(ticker) and current_ts_str:
        import pandas as pd
        ts = pd.Timestamp(current_ts_str)

        if is_in_dead_zone(ts):
            print(f"\n[3/5] In dead zone (NY lunch) — no trades during this window.")
            from journal.logger import log_low_confluence
            log_low_confluence(ticker, score, ict_context)
            broker.disconnect()
            return

        if not is_in_killzone(ts):
            print(f"\n[3/5] Outside kill zone — low probability window.")
            from journal.logger import log_low_confluence
            log_low_confluence(ticker, score, ict_context)
            broker.disconnect()
            return

    if score < MIN_CONFLUENCE_SCORE:
        print(f"\n[3/5] Score below threshold.")
        print(f"      Logging as low-confluence no-trade decision.")
        from journal.logger import log_low_confluence
        log_low_confluence(ticker, score, ict_context)
        _print_ict_summary(ict_context)
        broker.disconnect()
        return

    # Step 4: Trade Decision
    if USE_AI_ANALYSIS:
        print(f"[4/5] Sending to Claude API for ICT analysis...")
        try:
            from ai.analyst import analyze
            account_state = account.snapshot()
            account_state["open_position_count"] = get_open_trade_count()
            decision = analyze(ict_context, account_state)
        except Exception as e:
            print(f"  ERROR: AI analysis failed: {e}")
            broker.disconnect()
            return
    else:
        print(f"[4/5] Running rule-based trade decision...")
        from backtest.rules import decide_trade
        decision = decide_trade(ict_context)

    print(f"\n      Decision: {decision.get('decision', 'UNKNOWN')}")
    print(f"      Confidence: {decision.get('confidence', '?')}/10")
    print(f"      Setup: {decision.get('setup_type', '?')}")
    print(f"      HTF Bias: {decision.get('htf_bias', '?')}")

    if decision.get("entry_price"):
        print(f"\n      Entry:  {decision['entry_price']:.2f}")
        print(f"      SL:     {decision['stop_loss']:.2f}")
        print(f"      TP:     {decision['take_profit']:.2f}")
        print(f"      R:R:    {decision.get('risk_reward_ratio', '?')}")

    print(f"\n      Reasoning: {decision.get('reasoning', 'N/A')}")
    print(f"      Concepts: {', '.join(decision.get('ict_concepts_used', []))}")
    print(f"      Invalidation: {decision.get('invalidation', 'N/A')}")

    # Step 5: Execute via IBKR bracket order
    from journal import logger

    decision_type = decision.get("decision", "")

    if decision_type in ("LONG", "SHORT"):
        print(f"\n[5/5] Validating risk management...")
        valid, reason = validate_trade(
            decision, account, get_open_trade_count(), ticker=ticker
        )

        if valid:
            entry_price = decision["entry_price"]
            stop_loss = decision["stop_loss"]
            take_profit = decision["take_profit"]

            # Calculate futures contract quantity
            quantity = broker.calc_futures_quantity(
                account.balance, entry_price, stop_loss
            )
            risk_per_contract = abs(entry_price - stop_loss) * MES_POINT_VALUE
            total_risk = risk_per_contract * quantity

            print(f"      VALID — Placing IBKR bracket order")
            print(f"      Contracts: {quantity}")
            print(f"      Risk: ${total_risk:.2f} ({total_risk / account.balance * 100:.1f}% of account)")

            try:
                order_result = broker.place_bracket_order(
                    direction=decision_type,
                    quantity=quantity,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    contract=contract,
                )

                # Log to journal with broker order IDs
                position_data = {
                    "direction": decision_type,
                    "entry_price": entry_price,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "quantity": quantity,
                    "risk_amount": total_risk,
                    "status": "OPEN",
                    "broker_type": "ibkr",
                    "broker_order_ids": {
                        "parent": order_result["parent_order_id"],
                        "take_profit": order_result["tp_order_id"],
                        "stop_loss": order_result["sl_order_id"],
                    },
                }
                trade_id = logger.log_trade(
                    ticker=ticker,
                    position=position_data,
                    ai_decision=decision,
                    ict_context=ict_context,
                    account_before=account.balance,
                    account_after=account.balance,
                )
                print(f"      Order status: {order_result['status']}")
                print(f"      Parent order ID: {order_result['parent_order_id']}")
                print(f"      Trade logged: {trade_id}")
            except Exception as e:
                print(f"  ERROR: Failed to place bracket order: {e}")
                logger.log_no_trade(ticker, decision, ict_context, score)
        else:
            print(f"      REJECTED: {reason}")
            logger.log_no_trade(ticker, decision, ict_context, score)

    elif decision_type in ("CONDITIONAL_LONG", "CONDITIONAL_SHORT"):
        entry_zones = decision.get("entry_zones", [])
        print(f"\n[5/5] CONDITIONAL — {len(entry_zones)} entry zone(s) set")
        for i, zone in enumerate(entry_zones):
            priority = zone.get("priority", "?")
            z_type = zone.get("zone_type", "?")
            z_low = zone.get("zone_low", 0)
            z_high = zone.get("zone_high", 0)
            sl = zone.get("stop_loss", 0)
            tp1 = zone.get("take_profit_1", 0)
            rr = zone.get("risk_reward", "?")
            confirm = zone.get("confirmation_needed", "?")
            print(f"      Zone {i+1} (P{priority}): {z_type} {z_low:,.2f}-{z_high:,.2f}")
            print(f"        SL={sl:,.2f} TP={tp1:,.2f} R:R={rr}")
            print(f"        Confirmation: {confirm}")
            print(f"        Reason: {zone.get('reasoning', 'N/A')}")

        cond_id = logger.log_conditional_entry(ticker, decision, ict_context, score)
        print(f"\n      Conditional entry logged: {cond_id}")
        print(f"      Monitor will watch for price to enter zones.")

    else:
        print(f"\n[5/5] NO_TRADE — {decision.get('reasoning', 'N/A')}")
        logger.log_no_trade(ticker, decision, ict_context, score)

    broker.disconnect()
    print("\nDone.")


def cmd_check_positions():
    """Check open IBKR positions and orders."""
    from broker.ibkr import IBKRBroker

    broker = IBKRBroker()
    print("\nConnecting to IBKR...")
    try:
        broker.connect()
    except ConnectionError as e:
        print(f"  ERROR: {e}")
        return

    # Show account summary
    acct = broker.get_account_summary()
    print(f"\n  Account Balance: ${acct.get('balance', 0):,.2f}")
    if acct.get("unrealized_pnl") is not None:
        print(f"  Unrealized P&L:  ${acct['unrealized_pnl']:,.2f}")

    # Show positions
    positions = broker.get_positions()
    if positions:
        print(f"\n  Open Positions:")
        for p in positions:
            direction = "LONG" if p["quantity"] > 0 else "SHORT"
            print(f"    {p['symbol']} {direction} x{abs(p['quantity'])} @ avg {p['avg_cost']:.2f}")
    else:
        print(f"\n  No open positions.")

    # Show open orders
    orders = broker.get_open_orders()
    if orders:
        print(f"\n  Open Orders:")
        for o in orders:
            price = o.get("limit_price") or o.get("stop_price") or ""
            price_str = f"@ {price}" if price else ""
            parent_str = f" (child of #{o['parent_id']})" if o["parent_id"] else ""
            print(f"    #{o['order_id']} {o['action']} {o['quantity']}x {o['symbol']} "
                  f"{o['order_type']} {price_str} [{o['status']}]{parent_str}")
    else:
        print(f"\n  No open orders.")

    broker.disconnect()
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


def cmd_regime_test(
    data_path: str,
    ticker: str = "ES",
    balance: float | None = None,
    min_score: int | None = None,
    entry_tf: str = "15min",
    step: int | None = None,
    strategy: str = "default",
    start: str = "2021-08-01",
    end: str = "2025-01-01",
):
    """Run once over a span, then attribute the result across market regimes.

    This used to run four hardcoded one-week windows chosen by their realised
    return — three of which fell inside the holdout. Now the whole span runs once
    and results are split by regime afterwards, with each month labelled from the
    PRIOR month's trend efficiency and volatility so the label is knowable at the
    window's open.

    A config that only earns in one regime is a regime bet, not an edge.
    """
    from backtest.engine import run_backtest
    from backtest.regimes import attribute, classify_months, robustness
    from backtest.report import calc_stats
    from data.historical import load_continuous_contract

    balance = balance or STARTING_BALANCE
    min_score = min_score if min_score is not None else MIN_CONFLUENCE_SCORE

    print(f"\n{'='*60}")
    print(f"  ICT Regime Attribution")
    print(f"  Data: {data_path}")
    print(f"  Span: {start} to {end}   Ticker: {ticker}   Entry TF: {entry_tf}")
    print(f"  Strategy: {strategy}")
    print(f"{'='*60}")

    print("\n[1/3] Loading historical data...")
    try:
        df_1m = load_continuous_contract(data_path)
        print(f"      {len(df_1m):,} bars ({df_1m['timestamp'].min()} to {df_1m['timestamp'].max()})")
    except Exception as exc:
        print(f"  ERROR: Failed to load data: {exc}")
        return

    print("\n[2/3] Classifying months from prior-month signals...")
    classification = classify_months(df_1m, start, end)
    counts = classification.value_counts().to_dict()
    print(f"      {len(classification)} months labelled: {counts}")

    print("\n[3/3] Running the span once...")
    result = run_backtest(
        df_1m=df_1m, starting_balance=balance, min_score=min_score, ticker=ticker,
        entry_tf=entry_tf, step_bars=step, strategy=strategy,
        trade_start=pd.Timestamp(start, tz="UTC"),
        trade_end=pd.Timestamp(end, tz="UTC"),
    )
    stats = calc_stats(result)
    per_regime = attribute(stats.get("monthly_returns", {}), classification)
    summary = robustness(per_regime)

    print(f"\n  --- Overall ---")
    print(f"  Trades {stats.get('total_trades')}  WR {stats.get('win_rate')}%  "
          f"PF {stats.get('profit_factor')}  avg R {stats.get('avg_rr')}")
    print(f"  Net ${stats.get('net_pnl', 0):,.0f}  "
          f"(gross ${stats.get('gross_pnl', 0):,.0f} - costs ${stats.get('total_costs', 0):,.0f})")
    print(f"  Max drawdown {stats.get('max_drawdown_pct')}%")

    print(f"\n  --- By regime (labels are ex-ante) ---")
    print(f"  {'regime':20}{'months':>8}{'net P&L':>13}{'per month':>12}{'winning':>9}")
    for name, data in sorted(per_regime.items(), key=lambda kv: -kv[1]["pnl_per_month"]):
        print(f"  {name:20}{data['months']:>8}{data['net_pnl']:>13,.0f}"
              f"{data['pnl_per_month']:>12,.0f}{data['winning_months']:>6}/{data['months']}")

    if summary:
        print(f"\n  Profitable in {summary['regimes_profitable']} of "
              f"{summary['regimes_covered']} regimes.")
        print(f"  Worst: {summary['worst_regime']} at "
              f"${summary['worst_regime_pnl_per_month']:,.0f}/month")
        print(f"  Best:  {summary['best_regime']} at "
              f"${summary['best_regime_pnl_per_month']:,.0f}/month")
        if summary["regimes_profitable"] <= 1:
            print("  Earning in one regime only — that is a regime bet, not an edge.")
    print()


def cmd_backtest(
    data_path: str,
    ticker: str = "ES",
    balance: float | None = None,
    min_score: int | None = None,
    start: str | None = None,
    end: str | None = None,
    entry_tf: str = "15min",
    step: int | None = None,
    save_path: str | None = None,
    show_trades: int = 20,
    strategy: str = "default",
):
    """Run a walk-forward backtest on historical data."""
    from backtest.engine import run_backtest
    from backtest.report import print_report, print_trades, save_results, generate_equity_csv, generate_trade_log_csv
    from config import HTF_WARMUP_DAYS
    from data.historical import load_continuous_contract

    balance = balance or STARTING_BALANCE
    min_score = min_score if min_score is not None else MIN_CONFLUENCE_SCORE

    print(f"\n{'='*60}")
    print(f"  ICT Backtesting Engine")
    print(f"  Data: {data_path}")
    print(f"  Ticker: {ticker}")
    print(f"  Entry TF: {entry_tf}")
    print(f"  Balance: ${balance:,.2f}")
    print(f"  Min Score: {min_score}")
    print(f"  Strategy: {strategy}")
    print(f"{'='*60}\n")

    # Load data — extend start date for HTF warmup when needed
    load_start = start
    trade_start = None
    if start:
        warmup_start = pd.Timestamp(start) - pd.Timedelta(days=HTF_WARMUP_DAYS)
        load_start = warmup_start.strftime("%Y-%m-%d")
        trade_start = pd.Timestamp(start, tz="UTC")

    print("[1/3] Loading historical data...")
    try:
        df_1m = load_continuous_contract(data_path, start=load_start, end=end)
        if start:
            warmup_count = len(df_1m[df_1m["timestamp"] < trade_start])
            print(f"      Loaded {len(df_1m):,} bars ({df_1m['timestamp'].min()} to {df_1m['timestamp'].max()})")
            print(f"      HTF warmup: {warmup_count:,} bars before {start}")
        else:
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
        ticker=ticker,
        entry_tf=entry_tf,
        step_bars=step,
        strategy=strategy,
        trade_start=trade_start,
    )

    # Report
    print("[3/3] Generating report...")
    print_report(result)
    if show_trades:
        print_trades(result, limit=show_trades)

    # Save results
    from config import PROJECT_ROOT
    if save_path:
        save_results(result, save_path)
        eq_path = save_path.replace(".json", "_equity.csv")
        generate_equity_csv(result, eq_path)
        trade_log_path = save_path.replace(".json", "_trades.csv")
        generate_trade_log_csv(result, trade_log_path)
    else:
        default_path = str(PROJECT_ROOT / "logs" / "backtest_results.json")
        save_results(result, default_path)
        generate_trade_log_csv(result, str(PROJECT_ROOT / "logs" / "backtest_trades.csv"))


def cmd_optimize(
    data_path: str,
    ticker: str = "ES",
    entry_tf: str = "15min",
    thresholds: str = "30,40,50,60,70,80",
    balance: float | None = None,
    start: str | None = None,
    end: str | None = None,
):
    """Run walk-forward optimization of confluence threshold."""
    from backtest.optimize import optimize_threshold
    from data.historical import load_continuous_contract

    balance = balance or STARTING_BALANCE
    threshold_list = [int(t.strip()) for t in thresholds.split(",")]

    print(f"\n{'='*60}")
    print(f"  Walk-Forward Threshold Optimization")
    print(f"  Data: {data_path}")
    print(f"  Ticker: {ticker}")
    print(f"  Entry TF: {entry_tf}")
    print(f"  Thresholds: {threshold_list}")
    print(f"{'='*60}\n")

    # Load data with HTF warmup
    load_start = start
    if start:
        from config import HTF_WARMUP_DAYS
        warmup_start = pd.Timestamp(start) - pd.Timedelta(days=HTF_WARMUP_DAYS)
        load_start = warmup_start.strftime("%Y-%m-%d")

    df_1m = load_continuous_contract(data_path, start=load_start, end=end)
    print(f"  Loaded {len(df_1m):,} bars\n")

    trade_start = pd.Timestamp(start, tz="UTC") if start else None
    results = optimize_threshold(
        df_1m=df_1m,
        ticker=ticker,
        entry_tf=entry_tf,
        thresholds=threshold_list,
        starting_balance=balance,
        trade_start=trade_start,
    )

    # Print summary
    print(f"\n{'='*60}")
    print(f"  OPTIMIZATION RESULTS")
    print(f"{'='*60}")
    print(f"\n  --- Train Results ---")
    print(f"  {'Threshold':>10} {'Trades':>7} {'WR%':>6} {'PF':>6} {'P&L':>12} {'MaxDD':>7}")
    for r in results["train_results"]:
        pf_str = f"{r['profit_factor']:.2f}" if r["profit_factor"] != float("inf") else "inf"
        print(f"  {r['threshold']:>10} {r['trades']:>7} {r['win_rate']:>5.1f}% {pf_str:>6} ${r['pnl']:>10,.0f} {r['max_drawdown']:>6.1f}%")

    print(f"\n  Best threshold: {results['best_threshold']}")

    test = results["test_result"]
    pf_str = f"{test['profit_factor']:.2f}" if test["profit_factor"] != float("inf") else "inf"
    print(f"\n  --- Test Results (threshold={test['threshold']}) ---")
    print(f"  Trades: {test['trades']}, WR: {test['win_rate']}%, PF: {pf_str}")
    print(f"  P&L: ${test['pnl']:,.0f}, Max Drawdown: {test['max_drawdown']}%")


def cmd_download_history(
    symbol: str = "ES",
    days: int = 90,
    save: str | None = None,
):
    """Download historical 1m OHLCV data from IBKR."""
    import logging
    from broker.ibkr import IBKRBroker

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    print(f"\n  Downloading {days} days of 1m data for {symbol} from IBKR...")
    print(f"  This will make ~{days} API calls with 2s pacing (~{days * 2 // 60} min)\n")

    broker = IBKRBroker()
    try:
        broker.connect()
        df = broker.download_historical(
            symbol=symbol,
            duration_days=days,
            save_path=save,
        )
        print(f"\n  Done! {len(df):,} bars downloaded")
        print(f"  Range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    finally:
        broker.disconnect()


def main():
    parser = argparse.ArgumentParser(description="ICT Paper Trading Simulator")
    sub = parser.add_subparsers(dest="command")

    p_analyze = sub.add_parser("analyze", help="Run ICT analysis on a ticker")
    p_analyze.add_argument("ticker", help="Ticker symbol (e.g. AAPL, BTC-USD)")
    p_analyze.add_argument("--balance", type=float, help="Override starting balance")

    sub.add_parser("live", help="Start continuous live trading (streams bars, auto-analyzes)")

    sub.add_parser("check-positions", help="Check open IBKR positions and orders")

    sub.add_parser("stats", help="Show trading statistics")

    p_journal = sub.add_parser("journal", help="Show recent journal entries")
    p_journal.add_argument("--limit", type=int, default=10, help="Number of entries")

    p_opt = sub.add_parser("optimize", help="Walk-forward optimize confluence threshold")
    p_opt.add_argument("data", help="Path to OHLCV CSV file")
    p_opt.add_argument("--ticker", default="ES", help="Ticker symbol (default: ES)")
    p_opt.add_argument("--entry-tf", default="15min", help="Entry timeframe (default: 15min)")
    p_opt.add_argument("--thresholds", default="30,40,50,60,70,80", help="Comma-separated thresholds to test")
    p_opt.add_argument("--balance", type=float, help="Starting balance")
    p_opt.add_argument("--start", help="Start date (YYYY-MM-DD)")
    p_opt.add_argument("--end", help="End date (YYYY-MM-DD)")

    p_dl = sub.add_parser("download-history", help="Download historical 1m data from IBKR")
    p_dl.add_argument("--symbol", default="ES", help="Futures symbol (default: ES)")
    p_dl.add_argument("--days", type=int, default=90, help="Number of days (default: 90)")
    p_dl.add_argument("--save", help="Path to save CSV (auto-generated if omitted)")

    p_val = sub.add_parser("validate-data", help="Check a dataset before backtesting on it")
    p_val.add_argument("data", help="Path to a Databento .dbn.zst or CSV file")

    p_sweep = sub.add_parser("sweep", help="Run a named experiment sweep and record every cell")
    p_sweep.add_argument("name", help="Sweep name (see backtest/sweeps.py)")
    p_sweep.add_argument("data", help="Path to a Databento .dbn.zst or CSV file")
    p_sweep.add_argument("--ticker", default="ES", help="Ticker symbol (default: ES)")
    p_sweep.add_argument("--workers", type=int, help="Parallel workers (default: cores - 2)")
    p_sweep.add_argument("--span", default="screen",
                         choices=["screen", "train", "validate", "holdout"],
                         help="Date span: screen=2023 (default, fast), train=2021-2024, "
                              "holdout=2026 (look once, at the end)")

    p_rep = sub.add_parser("sweep-report", help="Rank everything in the experiment store")
    p_rep.add_argument("--top", type=int, default=15, help="Rows to show (default: 15)")

    p_bt = sub.add_parser("backtest", help="Run backtest on historical data")
    p_bt.add_argument("data", help="Path to OHLCV CSV file")
    p_bt.add_argument("--ticker", default="ES", help="Ticker symbol (default: ES). Use BTC-USD for crypto.")
    p_bt.add_argument("--balance", type=float, help="Starting balance (default: 100000)")
    p_bt.add_argument("--min-score", type=int, help="Min confluence score (default: 60)")
    p_bt.add_argument("--start", help="Start date (YYYY-MM-DD)")
    p_bt.add_argument("--end", help="End date (YYYY-MM-DD)")
    p_bt.add_argument("--entry-tf", default="15min", help="Entry timeframe: 1min, 5min, 15min (default: 15min)")
    p_bt.add_argument("--step", type=int, default=None, help="Analyze every Nth entry bar (auto-calculated if omitted)")
    p_bt.add_argument("--strategy", default="default",
                       choices=["default", "ict_2022", "silver_bullet"],
                       help="Trading strategy (default: confluence scoring)")
    p_bt.add_argument("--regime-test", action="store_true",
                       help="Run the span once, then attribute results per market regime "
                            "(labels computed from prior-month data only)")
    p_bt.add_argument("--save", help="Path to save results JSON")
    p_bt.add_argument("--trades", type=int, default=20, help="Number of recent trades to show")

    args = parser.parse_args()

    if args.command == "live":
        from live import LiveTrader
        trader = LiveTrader(ticker="MES")
        trader.start()
    elif args.command == "analyze":
        cmd_analyze(args.ticker, args.balance)
    elif args.command == "check-positions":
        cmd_check_positions()
    elif args.command == "stats":
        cmd_stats()
    elif args.command == "journal":
        cmd_journal(args.limit)
    elif args.command == "optimize":
        cmd_optimize(
            data_path=args.data,
            ticker=args.ticker,
            entry_tf=args.entry_tf,
            thresholds=args.thresholds,
            balance=args.balance,
            start=args.start,
            end=args.end,
        )
    elif args.command == "validate-data":
        from data.validate import validate
        findings = validate(args.data)
        sys.exit(1 if findings["problems"] else 0)
    elif args.command == "sweep":
        from backtest.experiments import run_matrix
        from backtest.sweeps import get_sweep
        cells = get_sweep(args.name, args.span)
        run_matrix(args.data, cells, ticker=args.ticker, max_workers=args.workers)
        print("\n  Run 'py main.py sweep-report' to rank results.")
    elif args.command == "sweep-report":
        from backtest.experiments import report
        report(top=args.top)
    elif args.command == "download-history":
        cmd_download_history(
            symbol=args.symbol,
            days=args.days,
            save=args.save,
        )
    elif args.command == "backtest":
        if args.regime_test:
            cmd_regime_test(
                data_path=args.data,
                ticker=args.ticker,
                balance=args.balance,
                min_score=args.min_score,
                entry_tf=args.entry_tf,
                step=args.step,
                strategy=args.strategy,
            )
        else:
            cmd_backtest(
                data_path=args.data,
                ticker=args.ticker,
                balance=args.balance,
                min_score=args.min_score,
                start=args.start,
                end=args.end,
                entry_tf=args.entry_tf,
                step=args.step,
                save_path=args.save,
                show_trades=args.trades,
                strategy=args.strategy,
            )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
