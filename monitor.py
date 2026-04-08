"""Real-time WebSocket position monitor.

Streams minute bars from Alpaca for all open positions.
Checks each bar against SL/TP levels for instant fill detection.

Usage:
    py monitor.py              # Run in foreground
    py monitor.py --daemon     # Run as background process
"""

import asyncio
import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import (
    MONITOR_CHECK_INTERVAL,
    TRADE_LOG_PATH,
    ticker_to_alpaca,
    alpaca_to_ticker,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MONITOR] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(__file__).parent / "logs" / "monitor.log"),
    ],
)
log = logging.getLogger(__name__)


def get_open_trades() -> list[dict]:
    """Load open trades from the journal."""
    try:
        with open(TRADE_LOG_PATH) as f:
            data = json.load(f)
        return [t for t in data.get("trades", []) if t.get("status") == "OPEN"]
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def close_trade_in_journal(trade_id: str, exit_price: float, exit_reason: str, pnl: float):
    """Update a trade in the journal as closed."""
    with open(TRADE_LOG_PATH) as f:
        data = json.load(f)

    for trade in data["trades"]:
        if trade["id"] == trade_id:
            trade["status"] = "CLOSED"
            trade["exit_price"] = exit_price
            trade["exit_reason"] = exit_reason
            trade["pnl_dollars"] = round(pnl, 2)
            trade["timestamp_closed"] = datetime.now(timezone.utc).isoformat()
            entry = trade["entry_price"]
            qty = trade.get("quantity", 0)
            if entry and qty:
                trade["pnl_pct"] = round(pnl / (entry * qty) * 100, 2)
            balance_before = trade.get("account_balance_before", 100000)
            trade["account_balance_after"] = round(balance_before + pnl, 2)
            break

    # Update metadata
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


def check_fill(trade: dict, bar: dict) -> dict | None:
    """Check if a bar's high/low crosses SL or TP.

    Returns fill info dict or None.
    """
    high = bar["high"]
    low = bar["low"]
    entry = trade["entry_price"]
    sl = trade["stop_loss"]
    tp = trade["take_profit"]
    direction = trade["direction"]
    qty = trade.get("quantity", 0)

    if direction == "LONG":
        if low <= sl:
            pnl = (sl - entry) * qty
            return {"exit_price": sl, "exit_reason": "SL_HIT", "pnl": pnl}
        if high >= tp:
            pnl = (tp - entry) * qty
            return {"exit_price": tp, "exit_reason": "TP_HIT", "pnl": pnl}
    elif direction == "SHORT":
        if high >= sl:
            pnl = (entry - sl) * qty
            return {"exit_price": sl, "exit_reason": "SL_HIT", "pnl": pnl}
        if low <= tp:
            pnl = (entry - tp) * qty
            return {"exit_price": tp, "exit_reason": "TP_HIT", "pnl": pnl}

    return None


class PositionMonitor:
    """Monitors open positions AND conditional entries via Alpaca WebSocket."""

    def __init__(self):
        self.open_trades: dict[str, list[dict]] = {}  # alpaca_symbol → [trades]
        self.conditionals: dict[str, list[dict]] = {}  # alpaca_symbol → [conditional entries]
        self.bar_buffer: dict[str, list[dict]] = {}   # symbol → recent bars for LTF confirmation
        self.BAR_BUFFER_SIZE = 20  # Keep last 20 minute bars per symbol

    def refresh_trades(self):
        """Reload open trades and conditional entries from journal."""
        trades = get_open_trades()
        self.open_trades.clear()
        for t in trades:
            alpaca_sym = ticker_to_alpaca(t["ticker"])
            if alpaca_sym not in self.open_trades:
                self.open_trades[alpaca_sym] = []
            self.open_trades[alpaca_sym].append(t)

        # Load active conditional entries
        from journal.logger import get_active_conditionals
        conditionals = get_active_conditionals()
        self.conditionals.clear()
        for c in conditionals:
            alpaca_sym = ticker_to_alpaca(c["ticker"])
            if alpaca_sym not in self.conditionals:
                self.conditionals[alpaca_sym] = []
            self.conditionals[alpaca_sym].append(c)

    def get_symbols_to_watch(self) -> list[str]:
        """Get all symbols that need monitoring (open trades + conditionals)."""
        symbols = set(self.open_trades.keys())
        symbols.update(self.conditionals.keys())
        return list(symbols)

    async def on_bar(self, symbol: str, bar: dict):
        """Called on each incoming minute bar from WebSocket."""
        # Buffer bars for LTF confirmation analysis
        if symbol not in self.bar_buffer:
            self.bar_buffer[symbol] = []
        self.bar_buffer[symbol].append(bar)
        if len(self.bar_buffer[symbol]) > self.BAR_BUFFER_SIZE:
            self.bar_buffer[symbol] = self.bar_buffer[symbol][-self.BAR_BUFFER_SIZE:]

        # 1. Check open positions for SL/TP fills
        trades = self.open_trades.get(symbol, [])
        for trade in trades[:]:
            fill = check_fill(trade, bar)
            if fill:
                log.info(
                    f"{'WIN' if fill['exit_reason'] == 'TP_HIT' else 'LOSS'}: "
                    f"{trade['ticker']} {trade['direction']} "
                    f"entry=${trade['entry_price']:.2f} "
                    f"exit=${fill['exit_price']:.2f} "
                    f"P&L=${fill['pnl']:.2f} "
                    f"({fill['exit_reason']})"
                )
                close_trade_in_journal(
                    trade["id"],
                    fill["exit_price"],
                    fill["exit_reason"],
                    fill["pnl"],
                )
                trades.remove(trade)
                if not trades:
                    del self.open_trades[symbol]
            else:
                current = bar["close"]
                if trade["direction"] == "LONG":
                    unrealized = (current - trade["entry_price"]) * trade.get("quantity", 0)
                else:
                    unrealized = (trade["entry_price"] - current) * trade.get("quantity", 0)
                log.debug(
                    f"{trade['ticker']} {trade['direction']} @ ${trade['entry_price']:.2f} "
                    f"| current=${current:.2f} | unrealized=${unrealized:.2f}"
                )

        # 2. Check conditional entries — is price in any entry zone?
        conditionals = self.conditionals.get(symbol, [])
        for cond in conditionals[:]:
            self._check_conditional(symbol, cond, bar)

    def _check_conditional(self, symbol: str, cond: dict, bar: dict):
        """Check if price has entered a conditional entry zone and if LTF confirms."""
        from journal.logger import update_conditional_status

        current = bar["close"]
        low = bar["low"]
        high = bar["high"]
        direction = cond.get("direction", "")

        # Check invalidation first
        invalidation = cond.get("invalidation", "")
        # Simple invalidation check: if price closes beyond a mentioned level
        # (More sophisticated parsing could be added)

        # Check each entry zone by priority order
        zones = sorted(cond.get("entry_zones", []), key=lambda z: z.get("priority", 99))

        for zone in zones:
            zone_low = zone.get("zone_low", 0)
            zone_high = zone.get("zone_high", 0)

            # Is price in this zone? Bar must overlap the zone AND not have blown through it.
            # LONG: bar low must be within or below zone, bar high must reach into zone, close still in/below zone
            # SHORT: bar high must be within or above zone, bar low must reach into zone, close still in/above zone
            price_in_zone = False
            if direction == "LONG" and low <= zone_high and high >= zone_low and current <= zone_high:
                price_in_zone = True
            elif direction == "SHORT" and high >= zone_low and low <= zone_high and current >= zone_low:
                price_in_zone = True

            if not price_in_zone:
                continue

            log.info(
                f"ZONE ALERT: {cond['ticker']} {direction} — price ${current:,.2f} "
                f"entered {zone['zone_type']} zone ${zone_low:,.2f}-${zone_high:,.2f} "
                f"(priority {zone.get('priority', '?')})"
            )

            # Determine confirmation timeframe based on zone's origin TF
            zone_tf = zone.get("zone_timeframe", "1h")
            from ict.confirmation import check_confirmation, get_confirmation_timeframe

            conf_params = get_confirmation_timeframe(zone_tf)
            log.info(
                f"  Zone from {zone_tf} → checking {conf_params['label']} confirmation"
            )

            # Fetch confirmation TF candles (REST call for proper multi-bar data)
            import pandas as pd
            try:
                ticker = cond["ticker"]
                from data.yahoo import fetch_ohlc
                conf_df = fetch_ohlc(ticker, conf_params["interval"], conf_params["range"])
            except Exception as e:
                log.warning(f"  Failed to fetch confirmation data: {e}")
                continue

            if len(conf_df) < 10:
                log.info(f"  Insufficient confirmation data ({len(conf_df)} bars)")
                continue

            confirmation = check_confirmation(
                conf_df,
                direction="bullish" if direction == "LONG" else "bearish",
                zone_low=zone_low,
                zone_high=zone_high,
                zone_timeframe=zone_tf,
            )

            if confirmation["confirmed"]:
                log.info(
                    f"  CONFIRMED! {confirmation['reason']} "
                    f"| Signals: {confirmation['signal_count']} "
                    f"({confirmation['strong_signal_count']} strong)"
                )

                # Execute the paper trade
                entry_price = confirmation.get("suggested_entry") or current
                self._execute_conditional(cond, zone, entry_price, confirmation)

                # Remove from conditionals
                if symbol in self.conditionals:
                    try:
                        self.conditionals[symbol].remove(cond)
                    except ValueError:
                        pass
                return  # Only trigger one zone
            else:
                log.debug(
                    f"  In zone but no confirmation yet: {confirmation['reason']}"
                )

    def _execute_conditional(self, cond: dict, zone: dict, entry_price: float, confirmation: dict):
        """Execute a confirmed conditional entry as a paper trade."""
        from journal.logger import log_trade, update_conditional_status
        from trading.account import Account
        from trading.risk import validate_trade

        ticker = cond["ticker"]
        direction = cond["direction"]

        # Build a trade decision from the conditional + zone
        decision = {
            "decision": direction,
            "entry_price": entry_price,
            "stop_loss": zone.get("stop_loss"),
            "take_profit": zone.get("take_profit_1"),
            "risk_reward_ratio": zone.get("risk_reward"),
        }

        # Get current account balance
        try:
            from journal.logger import load_journal
            journal = load_journal()
            balance = journal.get("metadata", {}).get("current_balance", 100000)
        except Exception:
            balance = 100000

        account = Account(starting_balance=balance, balance=balance)

        # Validate risk — load actual open position count from journal
        from journal.logger import get_open_trade_count
        open_count = get_open_trade_count()
        valid, reason = validate_trade(decision, account, open_count)
        if not valid:
            log.warning(f"  Trade rejected by risk management: {reason}")
            update_conditional_status(cond["id"], "INVALIDATED", {
                "invalidation_reason": f"Risk rejected: {reason}",
            })
            return

        # Open paper trade
        from trading.positions import PositionManager
        pm = PositionManager()
        pos = pm.open_position(decision, account, ticker)

        trade_id = log_trade(
            ticker=ticker,
            position=vars(pos),
            ai_decision={
                "decision": direction,
                "confidence": cond.get("confidence", 0),
                "reasoning": cond.get("reasoning", "") + f"\n\nCONDITIONAL TRIGGERED: {confirmation['reason']}",
                "ict_concepts_used": cond.get("ict_concepts_used", []),
                "setup_type": cond.get("setup_type", "conditional"),
                "htf_bias": cond.get("htf_bias", ""),
                "invalidation": cond.get("invalidation", ""),
                "risk_reward_ratio": zone.get("risk_reward"),
            },
            ict_context=cond.get("ict_context_snapshot", {}),
            account_before=account.balance,
            account_after=account.balance,
        )

        # Update conditional status
        update_conditional_status(cond["id"], "TRIGGERED", {
            "triggered_zone": zone,
            "triggered_at": datetime.now(timezone.utc).isoformat(),
            "confirmation_signals": confirmation.get("signals", []),
            "trade_id": trade_id,
        })

        log.info(
            f"  TRADE OPENED: {ticker} {direction} @ ${entry_price:,.2f} "
            f"SL=${zone['stop_loss']:,.2f} TP=${zone['take_profit_1']:,.2f} "
            f"R:R={zone.get('risk_reward', '?')} | ID={pos.id}"
        )

        # Add to open trades for SL/TP monitoring
        alpaca_sym = ticker_to_alpaca(ticker)
        if alpaca_sym not in self.open_trades:
            self.open_trades[alpaca_sym] = []
        self.open_trades[alpaca_sym].append({
            "id": trade_id,
            "ticker": ticker,
            "direction": direction,
            "entry_price": entry_price,
            "stop_loss": zone["stop_loss"],
            "take_profit": zone["take_profit_1"],
            "quantity": pos.quantity,
        })

    async def run(self):
        """Main monitoring loop."""
        from data.alpaca import stream_bars

        log.info("Position monitor starting...")

        while True:
            self.refresh_trades()
            symbols = self.get_symbols_to_watch()

            if not symbols:
                log.info(f"No open positions or conditionals. Checking again in {MONITOR_CHECK_INTERVAL}s...")
                await asyncio.sleep(MONITOR_CHECK_INTERVAL)
                continue

            open_count = sum(len(t) for t in self.open_trades.values())
            cond_count = sum(len(c) for c in self.conditionals.values())
            log.info(f"Monitoring {len(symbols)} symbol(s): {open_count} open trades, {cond_count} conditional entries")
            for sym, trades in self.open_trades.items():
                for t in trades:
                    log.info(
                        f"  {t['ticker']} {t['direction']} "
                        f"entry=${t['entry_price']:.2f} "
                        f"SL=${t['stop_loss']:.2f} "
                        f"TP=${t['take_profit']:.2f}"
                    )

            # Stream until all positions are closed or an error occurs
            # The stream_bars function handles reconnection internally
            try:
                # Create a task for streaming and a task for periodic trade refresh
                stream_task = asyncio.create_task(
                    stream_bars(symbols, self.on_bar)
                )
                refresh_task = asyncio.create_task(
                    self._periodic_refresh(stream_task)
                )

                # Wait for either to complete (stream runs forever, refresh may cancel it)
                done, pending = await asyncio.wait(
                    [stream_task, refresh_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                # Cancel pending tasks
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

            except Exception as e:
                log.error(f"Monitor error: {e}")
                await asyncio.sleep(5)

    async def _periodic_refresh(self, stream_task: asyncio.Task):
        """Periodically check for new/closed positions and restart stream if needed."""
        while True:
            await asyncio.sleep(MONITOR_CHECK_INTERVAL)
            old_symbols = set(self.open_trades.keys())
            self.refresh_trades()
            new_symbols = set(self.open_trades.keys())

            if new_symbols != old_symbols:
                log.info(f"Position change detected: {old_symbols} → {new_symbols}")
                if not new_symbols:
                    log.info("All positions closed. Stopping stream.")
                    stream_task.cancel()
                    return
                else:
                    # Need to restart stream with new symbols
                    log.info("Restarting stream for updated symbol list...")
                    stream_task.cancel()
                    return


def main():
    parser = argparse.ArgumentParser(description="ICT Paper Trader — Real-time Position Monitor")
    parser.add_argument("--daemon", action="store_true", help="Run as background daemon")
    args = parser.parse_args()

    monitor = PositionMonitor()

    if args.daemon:
        log.info("Running in daemon mode")

    try:
        asyncio.run(monitor.run())
    except KeyboardInterrupt:
        log.info("Monitor stopped by user")


if __name__ == "__main__":
    main()
