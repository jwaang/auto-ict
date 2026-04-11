"""Continuous live trading daemon — streams IBKR bars, analyzes, trades, monitors.

Replaces the old scheduled approach (run.py every 30 min) with a single
long-running process that:
1. Connects to IBKR once
2. Streams live 15m bars for the entry timeframe
3. On each new bar: runs full ICT analysis, places bracket orders if signaled
4. Monitors open bracket orders for SL/TP fills
5. Force-closes positions at session end (4 PM ET)

Usage:
    py main.py live          # Start live trading daemon
    py live.py               # Direct execution
"""

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from zoneinfo import ZoneInfo

from config import (
    IBKR_CLIENT_ID,
    IBKR_HOST,
    IBKR_PORT,
    MES_POINT_VALUE,
    MIN_CONFLUENCE_SCORE,
    TRADE_LOG_PATH,
    USE_AI_ANALYSIS,
    is_futures,
)

_ET = ZoneInfo("America/New_York")
_SESSION_END_HOUR = 16  # 4:00 PM ET

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [LIVE] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(__file__).parent / "logs" / "live.log"),
    ],
)
log = logging.getLogger(__name__)


class LiveTrader:
    """Unified live trading daemon: streaming + analysis + monitoring."""

    def __init__(self, ticker: str = "MES"):
        self.ticker = ticker
        self.broker = None
        self.contract = None

        # Cached DataFrames for each timeframe
        self._dataframes: dict = {}
        self._last_hourly_fetch: datetime | None = None
        self._last_daily_fetch: datetime | None = None

        # Live bar subscription
        self._entry_bars = None

        # Position tracking (from journal)
        self._tracked_orders: dict[int, dict] = {}  # parent_order_id → trade info

    # ─── Startup ────────────────────────────────────────────────────────

    def start(self):
        """Connect, fetch initial data, subscribe to live bars, and run."""
        log.info(f"Starting live trader for {self.ticker}")

        # Connect to IBKR
        from broker.ibkr import IBKRBroker
        self.broker = IBKRBroker()
        self.broker.connect(IBKR_HOST, IBKR_PORT, IBKR_CLIENT_ID)

        # Qualify contract
        self.contract = self.broker.get_mes_contract()
        log.info(f"Contract: {self.contract.localSymbol}")

        # Get account info
        acct = self.broker.get_account_summary()
        log.info(f"Account balance: ${acct.get('balance', 0):,.2f}")

        # Fetch initial historical data (one-time, ~15s)
        log.info("Fetching initial historical data...")
        self._fetch_all_timeframes()

        # Subscribe to live 15m bars
        log.info("Subscribing to live 15m bars...")
        self._entry_bars = self.broker.subscribe_bars(
            self.contract, bar_size="15 mins", duration="5 D"
        )
        self._entry_bars.updateEvent += self._on_entry_bar_update

        # Load any existing open positions
        self._load_tracked_orders()

        log.info("Live trader running. Waiting for bar updates...")
        self._print_status()

        # Main event loop
        try:
            self._run_loop()
        except KeyboardInterrupt:
            log.info("Shutting down...")
        finally:
            self._shutdown()

    # ─── Data Management ────────────────────────────────────────────────

    def _fetch_all_timeframes(self):
        """Fetch all historical data (bias, hourly, entry). Used at startup."""
        self._dataframes = self.broker.fetch_multi_timeframe(self.contract)
        self._last_daily_fetch = datetime.now(timezone.utc)
        self._last_hourly_fetch = datetime.now(timezone.utc)
        for label, df in self._dataframes.items():
            log.info(f"  {label}: {len(df)} bars")

    def _refresh_hourly_if_stale(self):
        """Re-fetch hourly data if it's been more than 1 hour."""
        if self._last_hourly_fetch is None:
            return
        elapsed = (datetime.now(timezone.utc) - self._last_hourly_fetch).total_seconds()
        if elapsed < 3600:
            return

        log.info("Refreshing hourly data (>1h since last fetch)...")
        try:
            bars = self.broker.ib.reqHistoricalData(
                self.contract,
                endDateTime="",
                durationStr="1 M",
                barSizeSetting="1 hour",
                whatToShow="TRADES",
                useRTH=False,
                formatDate=1,
            )
            if bars:
                hourly_df = self.broker._bars_to_dataframe(bars)
                self._dataframes["setup"] = hourly_df
                self._dataframes["swing"] = self.broker._aggregate_candles(hourly_df, "4h")
                self._last_hourly_fetch = datetime.now(timezone.utc)
                log.info(f"  setup: {len(hourly_df)} bars, swing: {len(self._dataframes['swing'])} bars")
        except Exception as e:
            log.warning(f"Failed to refresh hourly data: {e}")

    def _refresh_daily_if_stale(self):
        """Re-fetch daily data if it's been more than 1 day."""
        if self._last_daily_fetch is None:
            return
        elapsed = (datetime.now(timezone.utc) - self._last_daily_fetch).total_seconds()
        if elapsed < 86400:
            return

        log.info("Refreshing daily data (>1d since last fetch)...")
        try:
            bars = self.broker.ib.reqHistoricalData(
                self.contract,
                endDateTime="",
                durationStr="6 M",
                barSizeSetting="1 day",
                whatToShow="TRADES",
                useRTH=False,
                formatDate=1,
            )
            if bars:
                self._dataframes["bias"] = self.broker._bars_to_dataframe(bars)
                self._last_daily_fetch = datetime.now(timezone.utc)
                log.info(f"  bias: {len(self._dataframes['bias'])} bars")
        except Exception as e:
            log.warning(f"Failed to refresh daily data: {e}")

    # ─── Bar Update Handler ─────────────────────────────────────────────

    def _on_entry_bar_update(self, bars, hasNewBar):
        """Called when the 15m bar subscription updates.

        hasNewBar=True means a new completed bar is available.
        hasNewBar=False means the current (forming) bar updated.
        """
        if not hasNewBar:
            return  # Only act on completed bars

        # Update entry DataFrame — exclude the last bar (still forming)
        self._dataframes["entry"] = self.broker._bars_to_dataframe(bars[:-1])
        bar = bars[-2]  # The just-completed bar
        log.info(
            f"New 15m bar: {bar.date} | "
            f"O={bar.open} H={bar.high} L={bar.low} C={bar.close} V={bar.volume}"
        )

        # Refresh higher timeframes if stale
        self._refresh_hourly_if_stale()
        self._refresh_daily_if_stale()

        # Run analysis
        self._run_analysis()

    # ─── Analysis ───────────────────────────────────────────────────────

    def _run_analysis(self):
        """Run full ICT analysis and potentially place a trade."""
        from ict.confluence import analyze_multi_timeframe

        log.info("Running ICT analysis...")
        ict_context = analyze_multi_timeframe(self._dataframes, self.ticker)

        score = ict_context.get("confluence_score", 0)
        htf_bias = ict_context.get("htf_bias", "neutral")
        log.info(f"  HTF bias: {htf_bias} | Confluence: {score}/100")

        # Pre-flight checks
        from config import ENFORCE_KILL_ZONES
        from ict.killzones import is_in_dead_zone, is_in_killzone, is_crypto
        entry_data = ict_context.get("analyses", {}).get("entry", {})
        current_ts_str = entry_data.get("current_timestamp")

        if ENFORCE_KILL_ZONES and not is_crypto(self.ticker) and current_ts_str:
            import pandas as pd
            ts = pd.Timestamp(current_ts_str)

            if is_in_dead_zone(ts):
                log.info("  In dead zone (NY lunch) — skipping")
                return

            if not is_in_killzone(ts):
                log.info("  Outside kill zone — skipping")
                return

        if score < MIN_CONFLUENCE_SCORE:
            log.info(f"  Score {score} < {MIN_CONFLUENCE_SCORE} — skipping")
            return

        # Trade decision
        if USE_AI_ANALYSIS:
            from ai.analyst import analyze
            from trading.account import Account
            acct = self.broker.get_account_summary()
            balance = acct.get("balance", 100000)
            account = Account(starting_balance=balance, balance=balance)
            account_state = account.snapshot()
            from journal.logger import get_open_trade_count
            account_state["open_position_count"] = get_open_trade_count()
            decision = analyze(ict_context, account_state)
        else:
            from backtest.rules import decide_trade
            decision = decide_trade(ict_context)

        decision_type = decision.get("decision", "")
        log.info(f"  Decision: {decision_type} | {decision.get('reasoning', '')}")

        if decision_type not in ("LONG", "SHORT"):
            return

        # Validate and execute
        self._execute_trade(decision, ict_context, score)

    def _execute_trade(self, decision: dict, ict_context: dict, score: int):
        """Validate and place a bracket order on IBKR."""
        from journal import logger
        from journal.logger import get_open_trade_count
        from trading.account import Account
        from trading.risk import validate_trade

        acct = self.broker.get_account_summary()
        balance = acct.get("balance", 100000)
        account = Account(starting_balance=balance, balance=balance)

        valid, reason = validate_trade(
            decision, account, get_open_trade_count(), ticker=self.ticker
        )

        if not valid:
            log.info(f"  Trade rejected: {reason}")
            logger.log_no_trade(self.ticker, decision, ict_context, score)
            return

        entry_price = decision["entry_price"]
        stop_loss = decision["stop_loss"]
        take_profit = decision["take_profit"]
        direction = decision["decision"]

        quantity = self.broker.calc_futures_quantity(balance, entry_price, stop_loss)
        risk_per_contract = abs(entry_price - stop_loss) * MES_POINT_VALUE
        total_risk = risk_per_contract * quantity

        log.info(
            f"  PLACING ORDER: {direction} {quantity}x MES "
            f"@ {entry_price:.2f} SL={stop_loss:.2f} TP={take_profit:.2f} "
            f"risk=${total_risk:.2f}"
        )

        try:
            order_result = self.broker.place_bracket_order(
                direction=direction,
                quantity=quantity,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                contract=self.contract,
            )

            position_data = {
                "direction": direction,
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
                ticker=self.ticker,
                position=position_data,
                ai_decision=decision,
                ict_context=ict_context,
                account_before=balance,
                account_after=balance,
            )
            log.info(f"  Order placed! Trade ID: {trade_id} | Status: {order_result['status']}")

            # Add to tracked orders for fill monitoring
            self._tracked_orders[order_result["parent_order_id"]] = {
                **position_data,
                "id": trade_id,
                "ticker": self.ticker,
            }

        except Exception as e:
            log.error(f"  Failed to place order: {e}")
            logger.log_no_trade(self.ticker, decision, ict_context, score)

    # ─── Position Monitoring ────────────────────────────────────────────

    def _load_tracked_orders(self):
        """Load open trades from journal that have IBKR order IDs."""
        try:
            with open(TRADE_LOG_PATH) as f:
                data = json.load(f)
            trades = [t for t in data.get("trades", []) if t.get("status") == "OPEN"]
        except (FileNotFoundError, json.JSONDecodeError):
            trades = []

        self._tracked_orders.clear()
        for trade in trades:
            broker_ids = trade.get("broker_order_ids", {})
            parent_id = broker_ids.get("parent")
            if parent_id is not None:
                self._tracked_orders[parent_id] = trade
        if self._tracked_orders:
            log.info(f"Tracking {len(self._tracked_orders)} open position(s)")

    def _check_order_fills(self):
        """Check IBKR for filled bracket orders."""
        if not self._tracked_orders:
            return

        open_orders = self.broker.get_open_orders()
        open_order_ids = {o["order_id"] for o in open_orders}

        for parent_id, trade in list(self._tracked_orders.items()):
            broker_ids = trade.get("broker_order_ids", {})
            sl_order_id = broker_ids.get("stop_loss")
            tp_order_id = broker_ids.get("take_profit")

            sl_open = sl_order_id in open_order_ids
            tp_open = tp_order_id in open_order_ids

            if sl_open and tp_open:
                continue  # Both still open, position active

            if not sl_open and not tp_open:
                # Bracket completed — one side filled
                self._resolve_filled_bracket(trade, parent_id)

    def _resolve_filled_bracket(self, trade: dict, parent_id: int):
        """Determine which side of the bracket filled and log it."""
        entry = trade["entry_price"]
        sl = trade["stop_loss"]
        tp = trade["take_profit"]
        direction = trade["direction"]
        qty = trade.get("quantity", 0)

        broker_ids = trade.get("broker_order_ids", {})
        sl_order_id = broker_ids.get("stop_loss")
        tp_order_id = broker_ids.get("take_profit")

        fill_price = None
        exit_reason = None

        for fill in self.broker.ib.fills():
            if fill.execution.orderId == tp_order_id:
                fill_price = fill.execution.price
                exit_reason = "TP_HIT"
                break
            elif fill.execution.orderId == sl_order_id:
                fill_price = fill.execution.price
                exit_reason = "SL_HIT"
                break

        if fill_price is None:
            log.warning(f"Could not find fill for trade {trade['id']}, assuming SL")
            fill_price = sl
            exit_reason = "SL_HIT"

        if direction == "LONG":
            pnl = (fill_price - entry) * qty * MES_POINT_VALUE
        else:
            pnl = (entry - fill_price) * qty * MES_POINT_VALUE

        result = "WIN" if pnl > 0 else "LOSS"
        log.info(
            f"{result}: {self.ticker} {direction} "
            f"entry={entry:.2f} exit={fill_price:.2f} "
            f"P&L=${pnl:.2f} ({exit_reason})"
        )

        self._close_trade_in_journal(trade["id"], fill_price, exit_reason, pnl)
        del self._tracked_orders[parent_id]

    def _check_session_end(self):
        """Force-close all positions at 4 PM ET."""
        now_et = datetime.now(timezone.utc).astimezone(_ET)
        if now_et.hour < _SESSION_END_HOUR or now_et.weekday() >= 5:
            return
        if not self._tracked_orders:
            return

        log.info("Session end (4 PM ET) — closing all positions")
        self.broker.cancel_all_orders()
        time.sleep(1)

        positions = self.broker.get_positions()
        for pos in positions:
            if pos["quantity"] == 0:
                continue
            direction = "LONG" if pos["quantity"] > 0 else "SHORT"
            self.broker.place_market_order(direction=direction, quantity=abs(pos["quantity"]))

        price_data = self.broker.get_current_price()
        exit_price = price_data.get("last") or price_data.get("mid") or 0

        for parent_id, trade in list(self._tracked_orders.items()):
            entry = trade["entry_price"]
            direction = trade["direction"]
            qty = trade.get("quantity", 0)
            if direction == "LONG":
                pnl = (exit_price - entry) * qty * MES_POINT_VALUE
            else:
                pnl = (entry - exit_price) * qty * MES_POINT_VALUE
            log.info(f"SESSION END: {self.ticker} {direction} entry={entry:.2f} exit={exit_price:.2f} P&L=${pnl:.2f}")
            self._close_trade_in_journal(trade["id"], exit_price, "SESSION_END", pnl)

        self._tracked_orders.clear()

    @staticmethod
    def _close_trade_in_journal(trade_id: str, exit_price: float, exit_reason: str, pnl: float):
        """Update a trade in the journal as closed."""
        with open(TRADE_LOG_PATH) as f:
            data = json.load(f)

        # Derive current equity from the most recently closed trade, or starting balance
        closed_trades = [t for t in data["trades"] if t.get("status") == "CLOSED" and t.get("account_balance_after")]
        if closed_trades:
            sorted_closed = sorted(closed_trades, key=lambda t: t.get("timestamp_closed", ""), reverse=True)
            current_equity = sorted_closed[0]["account_balance_after"]
        else:
            current_equity = data.get("metadata", {}).get("current_balance", 100000)

        for trade in data["trades"]:
            if trade["id"] == trade_id:
                trade["status"] = "CLOSED"
                trade["exit_price"] = exit_price
                trade["exit_reason"] = exit_reason
                trade["pnl_dollars"] = round(pnl, 2)
                trade["timestamp_closed"] = datetime.now(timezone.utc).isoformat()
                risk = trade.get("risk_amount", 0)
                if risk:
                    trade["pnl_pct"] = round(pnl / risk * 100, 2)
                trade["account_balance_after"] = round(current_equity + pnl, 2)
                break

        closed_trades = [t for t in data["trades"] if t.get("status") == "CLOSED"]
        data["metadata"]["closed_trades"] = len(closed_trades)
        data["metadata"]["open_trades"] = len(data["trades"]) - len(closed_trades)
        data["metadata"]["last_updated"] = datetime.now(timezone.utc).isoformat()
        if closed_trades:
            balances = [t.get("account_balance_after", 0) for t in closed_trades if t.get("account_balance_after")]
            if balances:
                data["metadata"]["current_balance"] = balances[-1]

        with open(TRADE_LOG_PATH, "w") as f:
            json.dump(data, f, indent=2, default=str)

    # ─── Main Loop ──────────────────────────────────────────────────────

    def _run_loop(self):
        """Main event loop — let ib_insync process events, check fills."""
        last_status_print = 0

        while True:
            # Let ib_insync process incoming events (bar updates, order status)
            self.broker.ib.sleep(5)

            # Check for bracket order fills
            self._check_order_fills()

            # Check session end
            self._check_session_end()

            # Periodic status print (every 5 min)
            now = time.time()
            if now - last_status_print > 300:
                self._print_status()
                last_status_print = now

            # Reconnect if disconnected
            if not self.broker.connected:
                log.warning("IBKR disconnected — reconnecting...")
                try:
                    self.broker.connect(IBKR_HOST, IBKR_PORT, IBKR_CLIENT_ID)
                    self.contract = self.broker.get_mes_contract()
                    self._entry_bars = self.broker.subscribe_bars(
                        self.contract, bar_size="15 mins", duration="5 D"
                    )
                    self._entry_bars.updateEvent += self._on_entry_bar_update
                    self._fetch_all_timeframes()
                    log.info("Reconnected successfully")
                except Exception as e:
                    log.error(f"Reconnection failed: {e}. Retrying in 30s...")
                    time.sleep(30)

    def _print_status(self):
        """Print current status."""
        now_et = datetime.now(timezone.utc).astimezone(_ET)
        open_count = len(self._tracked_orders)
        entry_bars = len(self._dataframes.get("entry", []))
        log.info(
            f"Status: {now_et.strftime('%H:%M ET')} | "
            f"Entry bars: {entry_bars} | "
            f"Open positions: {open_count} | "
            f"Connected: {self.broker.connected}"
        )

    def _shutdown(self):
        """Clean shutdown."""
        if self._entry_bars is not None:
            try:
                self.broker.unsubscribe_bars(self._entry_bars)
            except Exception:
                pass
        if self.broker and self.broker.connected:
            self.broker.disconnect()
        log.info("Live trader stopped")


def main():
    trader = LiveTrader(ticker="MES")
    trader.start()


if __name__ == "__main__":
    main()
