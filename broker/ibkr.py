"""Interactive Brokers broker — connection, data, and order management via ib_insync.

Requires TWS or IB Gateway running in paper trading mode with API connections enabled.
No API keys needed — connects via local TCP socket.
"""

import logging
import math
import time
from datetime import date, datetime, timezone

import pandas as pd

from config import (
    IBKR_CLIENT_ID,
    IBKR_HOST,
    IBKR_PORT,
    MES_EXCHANGE,
    MES_POINT_VALUE,
    MES_TICK_SIZE,
    RISK_PER_TRADE_PCT,
)

try:
    from ib_insync import IB, Contract, Future, LimitOrder, MarketOrder, StopOrder, util
except ImportError:
    raise ImportError(
        "ib_insync is required for IBKR broker.\n"
        "Install it with: pip install ib_insync"
    )

log = logging.getLogger(__name__)


class IBKRBroker:
    """Interactive Brokers paper trading broker."""

    def __init__(self):
        self.ib = IB()
        self._contract: Contract | None = None

    # ─── Connection ─────────────────────────────────────────────────────

    def connect(
        self,
        host: str = IBKR_HOST,
        port: int = IBKR_PORT,
        client_id: int = IBKR_CLIENT_ID,
        timeout: int = 10,
    ):
        """Connect to TWS or IB Gateway.

        Args:
            host: TWS/Gateway host (default: 127.0.0.1)
            port: 7497 for TWS paper, 4002 for Gateway paper
            client_id: Unique client ID for this connection
            timeout: Connection timeout in seconds
        """
        if self.ib.isConnected():
            log.info("Already connected to IBKR")
            return

        log.info(f"Connecting to IBKR at {host}:{port} (clientId={client_id})...")
        try:
            self.ib.connect(host, port, clientId=client_id, timeout=timeout)
            log.info(f"Connected to IBKR — account: {self.ib.managedAccounts()}")
        except Exception as e:
            raise ConnectionError(
                f"Failed to connect to IBKR at {host}:{port}. "
                f"Ensure TWS or IB Gateway is running in paper trading mode "
                f"with API connections enabled on port {port}.\n"
                f"Error: {e}"
            ) from e

    def disconnect(self):
        """Disconnect from TWS/Gateway."""
        if self.ib.isConnected():
            self.ib.disconnect()
            log.info("Disconnected from IBKR")

    @property
    def connected(self) -> bool:
        return self.ib.isConnected()

    # ─── Contract ───────────────────────────────────────────────────────

    def get_mes_contract(self) -> Contract:
        """Get the front-month MES (Micro E-mini S&P 500) contract.

        Requests contract details for MES on CME and picks the nearest expiry
        (front-month) automatically.
        """
        if self._contract is not None:
            return self._contract

        # Use a generic MES future to search for available contracts
        generic = Future(symbol="MES", exchange=MES_EXCHANGE)
        details = self.ib.reqContractDetails(generic)

        if not details:
            raise RuntimeError(
                "No MES contracts found. "
                "Ensure you have CME market data subscription."
            )

        # Pick the nearest expiry (front-month)
        details.sort(key=lambda d: d.contract.lastTradeDateOrContractMonth)
        front_month = details[0].contract

        # Qualify the specific contract
        qualified = self.ib.qualifyContracts(front_month)
        if not qualified:
            raise RuntimeError(f"Failed to qualify MES contract: {front_month}")

        self._contract = qualified[0]
        log.info(
            f"MES contract: {self._contract.localSymbol} "
            f"(expiry: {self._contract.lastTradeDateOrContractMonth})"
        )
        return self._contract

    # ─── Market Data ────────────────────────────────────────────────────

    def fetch_multi_timeframe(self, contract: Contract | None = None) -> dict[str, pd.DataFrame]:
        """Fetch historical OHLC data for all 4 ICT timeframes.

        Returns dict with same format as data/yahoo.py fetch_multi_timeframe():
            {"bias": df, "swing": df, "setup": df, "entry": df}
        Each DataFrame has columns: timestamp, open, high, low, close, volume
        """
        if contract is None:
            contract = self.get_mes_contract()

        # 3 IBKR calls: daily, 1h (reused for swing+setup), 15m
        # swing (4H) is aggregated from the same 1H data as setup
        requests = {
            "bias": {"duration": "6 M", "bar_size": "1 day"},
            "hourly": {"duration": "1 M", "bar_size": "1 hour"},
            "entry": {"duration": "5 D", "bar_size": "15 mins"},
        }

        # Capture async errors from IBKR
        last_error = {}

        def on_error(reqId, errorCode, errorString, contract):
            last_error["code"] = errorCode
            last_error["msg"] = errorString
            log.warning(f"IBKR error {errorCode}: {errorString}")

        self.ib.errorEvent += on_error

        raw = {}
        for label, params in requests.items():
            last_error.clear()
            log.info(f"Fetching {label} data ({params['bar_size']})...")
            bars = self.ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr=params["duration"],
                barSizeSetting=params["bar_size"],
                whatToShow="TRADES",
                useRTH=False,
                formatDate=1,
            )

            if not bars:
                err_msg = last_error.get("msg", "unknown error")
                err_code = last_error.get("code", "?")
                raise RuntimeError(
                    f"No {label} data returned for {contract.localSymbol}. "
                    f"IBKR error {err_code}: {err_msg}"
                )

            raw[label] = self._bars_to_dataframe(bars)
            log.info(f"  {label}: {len(raw[label])} bars")

            # IBKR pacing: max 6 requests per 10 seconds
            time.sleep(2)

        self.ib.errorEvent -= on_error

        # Build 4 timeframes from 3 API calls
        results = {
            "bias": raw["bias"],
            "swing": self._aggregate_candles(raw["hourly"], "4h"),
            "setup": raw["hourly"],
            "entry": raw["entry"],
        }
        log.info(f"  swing: aggregated 1h → 4h → {len(results['swing'])} bars")

        return results

    def subscribe_bars(
        self,
        contract: Contract | None = None,
        bar_size: str = "15 mins",
        duration: str = "5 D",
    ):
        """Subscribe to live-updating historical bars.

        Uses reqHistoricalData with keepUpToDate=True to stream new bars
        as they complete. Returns a BarDataList that auto-updates.

        Attach a callback via: bars.updateEvent += on_update
        The callback signature is: on_update(bars, hasNewBar)
        When hasNewBar=True, a new bar has completed.

        Args:
            contract: Contract to stream (default: MES front month)
            bar_size: Bar size string (e.g. "15 mins", "1 hour")
            duration: Initial historical data duration

        Returns:
            BarDataList that updates in real-time
        """
        if contract is None:
            contract = self.get_mes_contract()

        bars = self.ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow="TRADES",
            useRTH=False,
            formatDate=1,
            keepUpToDate=True,
        )
        log.info(
            f"Subscribed to live {bar_size} bars for {contract.localSymbol} "
            f"({len(bars)} initial bars)"
        )
        return bars

    def unsubscribe_bars(self, bars):
        """Cancel a live bar subscription."""
        self.ib.cancelHistoricalData(bars)
        log.info("Unsubscribed from live bars")

    def get_current_price(self, contract: Contract | None = None) -> dict:
        """Get current bid/ask/last price snapshot.

        Returns:
            {"bid": float, "ask": float, "last": float, "mid": float}
        """
        if contract is None:
            contract = self.get_mes_contract()

        ticker = self.ib.reqMktData(contract, "", False, False)
        self.ib.sleep(2)  # Wait for data to arrive

        result = {
            "bid": ticker.bid if ticker.bid == ticker.bid else None,  # NaN check
            "ask": ticker.ask if ticker.ask == ticker.ask else None,
            "last": ticker.last if ticker.last == ticker.last else None,
        }

        # Calculate mid if bid/ask available
        if result["bid"] and result["ask"]:
            result["mid"] = (result["bid"] + result["ask"]) / 2
        else:
            result["mid"] = result["last"]

        self.ib.cancelMktData(contract)
        return result

    # ─── Order Management ───────────────────────────────────────────────

    def place_bracket_order(
        self,
        direction: str,
        quantity: int,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        contract: Contract | None = None,
    ) -> dict:
        """Place a bracket order (entry + SL + TP) on IBKR.

        Args:
            direction: "LONG" or "SHORT"
            quantity: Number of contracts (integer)
            entry_price: Limit price for entry order
            stop_loss: Stop price for stop-loss order
            take_profit: Limit price for take-profit order
            contract: Contract to trade (default: MES front month)

        Returns:
            dict with order IDs and status
        """
        if contract is None:
            contract = self.get_mes_contract()

        action = "BUY" if direction == "LONG" else "SELL"

        # Snap prices to MES tick size
        entry_price = self._snap_to_tick(entry_price)
        stop_loss = self._snap_to_tick(stop_loss)
        take_profit = self._snap_to_tick(take_profit)

        bracket = self.ib.bracketOrder(
            action=action,
            quantity=quantity,
            limitPrice=entry_price,
            takeProfitPrice=take_profit,
            stopLossPrice=stop_loss,
        )

        parent_order, tp_order, sl_order = bracket

        trades = []
        for order in bracket:
            trade = self.ib.placeOrder(contract, order)
            trades.append(trade)

        log.info(
            f"Bracket order placed: {direction} {quantity}x {contract.localSymbol} "
            f"@ {entry_price} | SL={stop_loss} TP={take_profit}"
        )
        log.info(
            f"  Order IDs — parent: {parent_order.orderId}, "
            f"TP: {tp_order.orderId}, SL: {sl_order.orderId}"
        )

        return {
            "parent_order_id": parent_order.orderId,
            "tp_order_id": tp_order.orderId,
            "sl_order_id": sl_order.orderId,
            "action": action,
            "quantity": quantity,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "status": trades[0].orderStatus.status,
            "trades": trades,
        }

    def place_market_order(
        self,
        direction: str,
        quantity: int,
        contract: Contract | None = None,
    ) -> dict:
        """Place a market order (for session-end close).

        Args:
            direction: "LONG" or "SHORT" (the position direction to close)
            quantity: Number of contracts

        Returns:
            dict with order ID and status
        """
        if contract is None:
            contract = self.get_mes_contract()

        # To close a position, reverse the direction
        action = "SELL" if direction == "LONG" else "BUY"
        order = MarketOrder(action, quantity)
        trade = self.ib.placeOrder(contract, order)

        log.info(f"Market order placed: {action} {quantity}x {contract.localSymbol}")
        return {
            "order_id": order.orderId,
            "action": action,
            "quantity": quantity,
            "status": trade.orderStatus.status,
            "trade": trade,
        }

    def cancel_all_orders(self):
        """Cancel all open orders."""
        self.ib.reqGlobalCancel()
        log.info("All open orders cancelled")

    # ─── Position / Account Queries ─────────────────────────────────────

    def get_positions(self) -> list[dict]:
        """Get all current positions."""
        positions = self.ib.positions()
        return [
            {
                "account": p.account,
                "symbol": p.contract.localSymbol,
                "quantity": p.position,
                "avg_cost": p.avgCost,
                "contract": p.contract,
            }
            for p in positions
        ]

    def get_open_orders(self) -> list[dict]:
        """Get all open/pending orders."""
        trades = self.ib.openTrades()
        return [
            {
                "order_id": t.order.orderId,
                "symbol": t.contract.localSymbol,
                "action": t.order.action,
                "quantity": t.order.totalQuantity,
                "order_type": t.order.orderType,
                "limit_price": t.order.lmtPrice,
                "stop_price": t.order.auxPrice,
                "status": t.orderStatus.status,
                "parent_id": t.order.parentId,
            }
            for t in trades
        ]

    def get_account_summary(self) -> dict:
        """Get account balance and key metrics."""
        values = self.ib.accountValues()
        summary = {}
        for v in values:
            if v.tag == "NetLiquidation" and v.currency == "USD":
                summary["balance"] = float(v.value)
            elif v.tag == "BuyingPower":
                summary["buying_power"] = float(v.value)
            elif v.tag == "TotalCashValue" and v.currency == "USD":
                summary["cash"] = float(v.value)
            elif v.tag == "UnrealizedPnL" and v.currency == "USD":
                summary["unrealized_pnl"] = float(v.value)
            elif v.tag == "RealizedPnL" and v.currency == "USD":
                summary["realized_pnl"] = float(v.value)
        return summary

    # ─── Position Sizing ────────────────────────────────────────────────

    @staticmethod
    def calc_futures_quantity(
        balance: float,
        entry_price: float,
        stop_loss: float,
        risk_pct: float = RISK_PER_TRADE_PCT,
        point_value: float = MES_POINT_VALUE,
    ) -> int:
        """Calculate number of futures contracts based on risk.

        Args:
            balance: Account balance
            entry_price: Entry price
            stop_loss: Stop loss price
            risk_pct: Risk percentage per trade (default: 1%)
            point_value: Dollar value per point (MES = $5)

        Returns:
            Number of contracts (integer, minimum 1)
        """
        risk_amount = balance * (risk_pct / 100)
        sl_distance = abs(entry_price - stop_loss)
        risk_per_contract = sl_distance * point_value

        if risk_per_contract <= 0:
            return 0

        quantity = math.floor(risk_amount / risk_per_contract)
        return max(1, quantity)

    # ─── Internal Helpers ───────────────────────────────────────────────

    @staticmethod
    def _bars_to_dataframe(bars) -> pd.DataFrame:
        """Convert ib_insync BarDataList to DataFrame matching the standard format."""
        rows = []
        for bar in bars:
            # ib_insync returns bar.date as datetime for intraday, date for daily
            ts = bar.date
            if isinstance(ts, date) and not isinstance(ts, datetime):
                # Daily bars: convert date to datetime at midnight UTC
                ts = datetime(ts.year, ts.month, ts.day, tzinfo=timezone.utc)
            elif ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            rows.append({
                "timestamp": ts,
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": int(bar.volume),
            })
        return pd.DataFrame(rows)

    @staticmethod
    def _aggregate_candles(df: pd.DataFrame, target_interval: str) -> pd.DataFrame:
        """Aggregate candles to a higher timeframe (e.g. 1h → 4h)."""
        df = df.copy()
        df["ts_agg"] = df["timestamp"].dt.floor(target_interval.replace("h", "h"))
        agg = df.groupby("ts_agg").agg({
            "timestamp": "first",
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).reset_index(drop=True)
        return agg

    @staticmethod
    def _snap_to_tick(price: float, tick_size: float = MES_TICK_SIZE) -> float:
        """Snap a price to the nearest valid tick."""
        return round(round(price / tick_size) * tick_size, 2)
