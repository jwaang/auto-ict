"""Streamlit dashboard for ICT Paper Trading Simulator."""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

st.set_page_config(page_title="ICT Paper Trader", page_icon="📊", layout="wide")


def main():
    st.title("ICT Paper Trading Simulator")

    # Sidebar controls
    with st.sidebar:
        st.header("Controls")
        ticker = st.text_input("Ticker Symbol", value="MES", help="MES (Micro E-mini S&P 500)", disabled=True)
        balance_override = st.number_input(
            "Starting Balance", value=100_000.0, step=1000.0, format="%.2f"
        )
        analyze_btn = st.button("🔍 Run ICT Analysis", use_container_width=True, type="primary")
        check_btn = st.button("📋 Check Open Positions", use_container_width=True)

        st.divider()
        _show_account_summary()

    # Main content tabs
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Dashboard", "🔬 Analysis", "📜 Trade History", "📈 Statistics"])

    with tab1:
        _tab_dashboard()

    with tab2:
        if analyze_btn:
            _tab_analysis(ticker, balance_override)
        elif check_btn:
            _tab_check_positions(ticker)
        else:
            st.info("Click **Run ICT Analysis** in the sidebar to analyze a ticker.")

    with tab3:
        _tab_trade_history()

    with tab4:
        _tab_statistics()


def _show_account_summary():
    """Show account summary in sidebar."""
    try:
        from journal.logger import load_journal
        data = load_journal()
        meta = data.get("metadata", {})
        balance = meta.get("current_balance", 100_000)
        total = meta.get("total_trades", 0)
        st.metric("Balance", f"${balance:,.2f}")
        st.metric("Total Trades", total)
    except Exception:
        st.metric("Balance", "$100,000.00")


def _tab_dashboard():
    """Dashboard tab — equity curve, open positions, key metrics."""
    st.subheader("Portfolio Dashboard")

    try:
        from journal.logger import get_stats, load_journal
        stats = get_stats()
        data = load_journal()

        # Key metrics
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Net P&L", f"${stats.get('net_pnl', 0):,.2f}")
        with col2:
            st.metric("Win Rate", f"{stats.get('win_rate', 0)}%")
        with col3:
            st.metric("Profit Factor", f"{stats.get('profit_factor', 0):.2f}")
        with col4:
            st.metric("Avg R:R", f"{stats.get('avg_rr', 0):.2f}")

        # Equity curve
        trades = [t for t in data.get("trades", []) if t.get("status") == "CLOSED"]
        if trades:
            import pandas as pd
            balances = []
            for t in trades:
                balances.append({
                    "Trade": len(balances) + 1,
                    "Balance": t.get("account_balance_after", 100_000),
                })
            eq_df = pd.DataFrame(balances)
            st.line_chart(eq_df.set_index("Trade"))

        # Open positions
        open_trades = [t for t in data.get("trades", []) if t.get("status") == "OPEN"]
        if open_trades:
            st.subheader("Open Positions")
            for t in open_trades:
                with st.container(border=True):
                    c1, c2, c3, c4 = st.columns(4)
                    c1.write(f"**{t['ticker']}** {t['direction']}")
                    c2.write(f"Entry: ${t['entry_price']:.2f}")
                    c3.write(f"SL: ${t['stop_loss']:.2f}")
                    c4.write(f"TP: ${t['take_profit']:.2f}")
        else:
            st.info("No open positions")

    except Exception as e:
        st.warning(f"No data yet. Run an analysis first. ({e})")


def _tab_analysis(ticker: str, balance: float):
    """Analysis tab — run ICT analysis and show results."""
    st.subheader(f"ICT Analysis: {ticker}")

    with st.spinner(f"Fetching OHLC data from IBKR for {ticker}..."):
        try:
            from broker.ibkr import IBKRBroker
            broker = IBKRBroker()
            broker.connect()
            dataframes = broker.fetch_multi_timeframe()
            broker.disconnect()
        except Exception as e:
            st.error(f"Failed to fetch data: {e}")
            return

    for label, df in dataframes.items():
        st.write(f"**{label}**: {len(df)} candles")

    with st.spinner("Running ICT detection engine..."):
        from ict.confluence import analyze_multi_timeframe
        ict_context = analyze_multi_timeframe(dataframes, ticker)

    score = ict_context.get("confluence_score", 0)

    # Show ICT levels
    st.subheader("Detected ICT Levels")
    for tf_label, tf_data in ict_context.get("analyses", {}).items():
        with st.expander(f"**{tf_label.upper()}** — Bias: {tf_data.get('bias', '?')}", expanded=(tf_label == "entry")):
            col1, col2 = st.columns(2)
            with col1:
                st.write("**Fair Value Gaps (unfilled)**")
                for f in tf_data.get("unfilled_fvgs", [])[-5:]:
                    st.write(f"  {f['type']}: ${f['bottom']:.2f} - ${f['top']:.2f}")
                st.write("**Order Blocks (unmitigated)**")
                for ob in tf_data.get("unmitigated_obs", [])[-5:]:
                    st.write(f"  {ob['type']}: ${ob['low']:.2f} - ${ob['high']:.2f}")
            with col2:
                st.write("**Displacements**")
                for d in tf_data.get("displacements", [])[-3:]:
                    st.write(f"  {d['direction']} ({d['body_atr_ratio']}x ATR)")
                st.write(f"**Premium/Discount**: {tf_data.get('premium_discount', {}).get('zone', '?')}")
                ote = tf_data.get("ote", {})
                if ote.get("valid"):
                    st.write(f"**OTE**: ${ote['ote_low']:.2f} - ${ote['ote_high']:.2f}")
                st.write(f"**Kill Zone**: {tf_data.get('kill_zone') or 'None'}")

    # Confluence score
    st.metric("Confluence Score", f"{score}/100")
    st.progress(score / 100)

    from config import MIN_CONFLUENCE_SCORE
    if score < MIN_CONFLUENCE_SCORE:
        st.warning(f"Score below {MIN_CONFLUENCE_SCORE} — no trade setup detected.")
        from journal.logger import log_low_confluence
        log_low_confluence(ticker, score, ict_context)
        return

    # AI Analysis
    st.subheader("AI Trade Decision")
    with st.spinner("Consulting Claude API..."):
        try:
            from ai.analyst import analyze
            from trading.account import Account
            account = Account(starting_balance=balance)
            account_state = account.snapshot()
            decision = analyze(ict_context, account_state)
        except Exception as e:
            st.error(f"AI analysis failed: {e}")
            return

    # Display decision
    decision_type = decision.get("decision", "UNKNOWN")
    if decision_type == "LONG":
        st.success(f"**{decision_type}** — Confidence: {decision.get('confidence', '?')}/10")
    elif decision_type == "SHORT":
        st.error(f"**{decision_type}** — Confidence: {decision.get('confidence', '?')}/10")
    else:
        st.info(f"**{decision_type}** — Confidence: {decision.get('confidence', '?')}/10")

    if decision.get("entry_price"):
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Entry", f"${decision['entry_price']:.2f}")
        col2.metric("Stop Loss", f"${decision['stop_loss']:.2f}")
        col3.metric("Take Profit", f"${decision['take_profit']:.2f}")
        col4.metric("R:R", f"{decision.get('risk_reward_ratio', '?')}")

    st.write(f"**Setup**: {decision.get('setup_type', '?')}")
    st.write(f"**HTF Bias**: {decision.get('htf_bias', '?')}")
    st.write(f"**Concepts**: {', '.join(decision.get('ict_concepts_used', []))}")

    with st.expander("Full Reasoning"):
        st.write(decision.get("reasoning", "N/A"))

    st.write(f"**Invalidation**: {decision.get('invalidation', 'N/A')}")

    # Paper trade execution via IBKR
    if decision_type in ("LONG", "SHORT"):
        from trading.account import Account
        from trading.risk import validate_trade
        from journal import logger

        if st.button(f"Execute Paper Trade ({decision_type})", type="primary"):
            try:
                from broker.ibkr import IBKRBroker
                from config import MES_POINT_VALUE
                broker = IBKRBroker()
                broker.connect()

                # Use real IBKR account balance for sizing
                acct = broker.get_account_summary()
                ibkr_balance = acct.get("balance", balance)
                account = Account(starting_balance=ibkr_balance, balance=ibkr_balance)
                valid, reason = validate_trade(decision, account, 0, ticker=ticker)

                if not valid:
                    broker.disconnect()
                    st.warning(f"Trade rejected by risk management: {reason}")
                    logger.log_no_trade(ticker, decision, ict_context, score)
                    return

                entry_price = decision["entry_price"]
                stop_loss = decision["stop_loss"]
                take_profit = decision["take_profit"]
                quantity = broker.calc_futures_quantity(ibkr_balance, entry_price, stop_loss)
                order_result = broker.place_bracket_order(
                    direction=decision_type, quantity=quantity,
                    entry_price=entry_price, stop_loss=stop_loss, take_profit=take_profit,
                )
                risk = abs(entry_price - stop_loss) * MES_POINT_VALUE * quantity
                    position_data = {
                        "direction": decision_type, "entry_price": entry_price,
                        "stop_loss": stop_loss, "take_profit": take_profit,
                        "quantity": quantity, "risk_amount": risk, "status": "OPEN",
                        "broker_type": "ibkr",
                        "broker_order_ids": {
                            "parent": order_result["parent_order_id"],
                            "take_profit": order_result["tp_order_id"],
                            "stop_loss": order_result["sl_order_id"],
                        },
                    }
                    logger.log_trade(
                        ticker=ticker, position=position_data, ai_decision=decision,
                        ict_context=ict_context, account_before=ibkr_balance, account_after=ibkr_balance,
                    )
                    broker.disconnect()
                    st.success(f"Bracket order placed on IBKR! Status: {order_result['status']}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to place order: {e}")


def _tab_check_positions(ticker: str | None = None):
    """Check open positions for SL/TP fills."""
    st.subheader("Position Check")
    from journal.logger import load_journal
    data = load_journal()
    open_trades = [t for t in data.get("trades", []) if t.get("status") == "OPEN"]

    if not open_trades:
        st.info("No open positions to check.")
        return

    try:
        from broker.ibkr import IBKRBroker
        broker = IBKRBroker()
        broker.connect()
        price = broker.get_current_price()
        for trade in open_trades:
            current = price.get("last") or price.get("mid") or 0
            st.write(f"**{trade['ticker']}** {trade['direction']} @ ${trade['entry_price']:.2f}")
            st.write(f"Current: ${current:.2f} | SL: ${trade['stop_loss']:.2f} | TP: ${trade['take_profit']:.2f}")
        broker.disconnect()
    except Exception as e:
        st.error(f"Error connecting to IBKR: {e}")


def _tab_trade_history():
    """Trade history tab — sortable table with expandable reasoning."""
    st.subheader("Trade History")
    try:
        from journal.logger import load_journal
        data = load_journal()
        trades = data.get("trades", [])

        if not trades:
            st.info("No trades yet. Run an analysis to get started.")
            return

        for t in reversed(trades):
            status = t.get("status", "?")
            icon = "🟢" if status == "CLOSED" and (t.get("pnl_dollars") or 0) > 0 else "🔴" if status == "CLOSED" else "🟡"
            pnl = t.get("pnl_dollars")
            pnl_str = f"${pnl:+,.2f}" if pnl is not None else "Open"

            with st.expander(f"{icon} {t['ticker']} {t['direction']} @ ${t['entry_price']:.2f} → {pnl_str}"):
                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"**Entry**: ${t['entry_price']:.2f}")
                    st.write(f"**SL**: ${t['stop_loss']:.2f}")
                    st.write(f"**TP**: ${t['take_profit']:.2f}")
                    st.write(f"**Quantity**: {t.get('quantity', '?')}")
                with col2:
                    st.write(f"**Exit**: ${t['exit_price']:.2f}" if t.get("exit_price") else "**Exit**: Pending")
                    st.write(f"**Reason**: {t.get('exit_reason', 'N/A')}")
                    st.write(f"**P&L**: {pnl_str}")
                    st.write(f"**Status**: {status}")

                ai = t.get("ai_decision", {})
                st.write(f"**Setup**: {ai.get('setup_type', '?')}")
                st.write(f"**Concepts**: {', '.join(ai.get('ict_concepts_used', []))}")
                st.write(f"**Reasoning**: {ai.get('reasoning', 'N/A')}")

        # No-trade decisions
        no_trades = data.get("no_trade_decisions", [])
        if no_trades:
            st.subheader("No-Trade Decisions")
            for nt in reversed(no_trades[-10:]):
                with st.expander(f"⬜ {nt.get('ticker', '?')} — Score: {nt.get('confluence_score', '?')}"):
                    st.write(nt.get("reasoning", "N/A"))

    except Exception as e:
        st.warning(f"No trade history yet. ({e})")


def _tab_statistics():
    """Statistics tab — performance metrics."""
    st.subheader("Trading Statistics")
    try:
        from journal.logger import get_stats
        stats = get_stats()

        if stats["total_trades"] == 0:
            st.info("No closed trades yet.")
            return

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Trades", stats["total_trades"])
            st.metric("Wins", stats["wins"])
            st.metric("Losses", stats["losses"])
        with col2:
            st.metric("Win Rate", f"{stats['win_rate']}%")
            st.metric("Profit Factor", f"{stats['profit_factor']:.2f}")
            st.metric("Avg R:R", f"{stats['avg_rr']:.2f}")
        with col3:
            st.metric("Net P&L", f"${stats['net_pnl']:,.2f}")
            st.metric("Best Trade", f"${stats['best_trade']:,.2f}")
            st.metric("Worst Trade", f"${stats['worst_trade']:,.2f}")

    except Exception as e:
        st.warning(f"No statistics available yet. ({e})")


if __name__ == "__main__":
    main()
