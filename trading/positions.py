"""Position lifecycle — open, monitor, close paper trades."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from trading.account import Account
from trading.risk import calc_risk_reward


@dataclass
class Position:
    id: str
    ticker: str
    direction: str  # "LONG" or "SHORT"
    entry_price: float
    stop_loss: float
    take_profit: float
    quantity: float
    risk_amount: float
    entry_time: str
    status: str = "OPEN"  # OPEN, CLOSED
    exit_price: float | None = None
    exit_reason: str | None = None  # TP_HIT, SL_HIT, MANUAL
    exit_time: str | None = None
    pnl_dollars: float | None = None
    pnl_pct: float | None = None


class PositionManager:
    def __init__(self):
        self.positions: list[Position] = []

    def open_position(self, decision: dict, account: Account, ticker: str) -> Position:
        """Open a new paper trade position.

        Args:
            decision: AI trade decision dict with entry/SL/TP
            account: Account for position sizing
            ticker: Ticker symbol

        Returns:
            New Position
        """
        entry = decision["entry_price"]
        sl = decision["stop_loss"]
        tp = decision["take_profit"]
        direction = decision["decision"]

        quantity = account.get_position_size(entry, sl)
        risk_amount = account.get_risk_amount()

        pos = Position(
            id=str(uuid.uuid4())[:8],
            ticker=ticker,
            direction=direction,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            quantity=round(quantity, 4),
            risk_amount=round(risk_amount, 2),
            entry_time=datetime.now(timezone.utc).isoformat(),
        )
        self.positions.append(pos)
        return pos

    def check_fills(self, candle: dict) -> list[dict]:
        """Check if any open positions hit SL or TP based on a candle.

        Args:
            candle: Dict with high, low keys (from latest candle data)

        Returns:
            List of fill events
        """
        fills = []
        high = candle["high"]
        low = candle["low"]

        for pos in self.get_open_positions():
            fill = self._check_position_fill(pos, high, low)
            if fill:
                fills.append(fill)

        return fills

    def _check_position_fill(self, pos: Position, high: float, low: float) -> dict | None:
        """Check if a single position was filled by this candle's range."""
        if pos.direction == "LONG":
            # SL hit if low <= stop_loss
            if low <= pos.stop_loss:
                return self._close(pos, pos.stop_loss, "SL_HIT")
            # TP hit if high >= take_profit
            if high >= pos.take_profit:
                return self._close(pos, pos.take_profit, "TP_HIT")
        else:  # SHORT
            # SL hit if high >= stop_loss
            if high >= pos.stop_loss:
                return self._close(pos, pos.stop_loss, "SL_HIT")
            # TP hit if low <= take_profit
            if low <= pos.take_profit:
                return self._close(pos, pos.take_profit, "TP_HIT")
        return None

    def _close(self, pos: Position, exit_price: float, reason: str) -> dict:
        """Close a position and calculate P&L."""
        if pos.direction == "LONG":
            pnl = (exit_price - pos.entry_price) * pos.quantity
        else:
            pnl = (pos.entry_price - exit_price) * pos.quantity

        pos.status = "CLOSED"
        pos.exit_price = exit_price
        pos.exit_reason = reason
        pos.exit_time = datetime.now(timezone.utc).isoformat()
        pos.pnl_dollars = round(pnl, 2)
        pos.pnl_pct = round(pnl / (pos.entry_price * pos.quantity) * 100, 2) if pos.entry_price else 0

        return {
            "position_id": pos.id,
            "ticker": pos.ticker,
            "direction": pos.direction,
            "entry_price": pos.entry_price,
            "exit_price": exit_price,
            "exit_reason": reason,
            "pnl_dollars": pos.pnl_dollars,
            "pnl_pct": pos.pnl_pct,
            "rr_achieved": calc_risk_reward(pos.entry_price, pos.stop_loss, exit_price),
        }

    def close_position_manual(self, position_id: str, exit_price: float) -> dict | None:
        """Manually close a position at a given price."""
        for pos in self.positions:
            if pos.id == position_id and pos.status == "OPEN":
                return self._close(pos, exit_price, "MANUAL")
        return None

    def get_open_positions(self) -> list[Position]:
        """Return all open positions."""
        return [p for p in self.positions if p.status == "OPEN"]

    def get_closed_positions(self) -> list[Position]:
        """Return all closed positions."""
        return [p for p in self.positions if p.status == "CLOSED"]

    def get_open_count(self) -> int:
        return len(self.get_open_positions())

    def to_dicts(self) -> list[dict]:
        """Serialize all positions to dicts."""
        return [vars(p) for p in self.positions]
