"""Position lifecycle — open, monitor, close paper trades."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import math

from config import (
    BE_MOVE_THRESHOLD_R,
    PARTIAL_CLOSE_PCT,
    SLIPPAGE_POINTS,
    SPREAD_POINTS,
    TRADE_MANAGEMENT_ENABLED,
)
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
    requested_entry_price: float | None = None  # Pre-spread entry price
    # Trade management fields
    original_stop_loss: float | None = None
    original_quantity: float = 0.0
    partial_fills: list = field(default_factory=list)
    current_stage: int = 0   # 0=initial, 1=partial taken + trailing
    trailing_sl: float | None = None


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
        raw_entry = decision["entry_price"]
        sl = decision["stop_loss"]
        tp = decision["take_profit"]
        direction = decision["decision"]

        # Apply half-spread to entry (LONG pays more, SHORT gets less)
        half_spread = SPREAD_POINTS / 2
        if direction == "LONG":
            entry = raw_entry + half_spread
        else:
            entry = raw_entry - half_spread

        quantity = account.get_position_size(entry, sl)
        risk_amount = account.get_risk_amount()

        pos = Position(
            id=str(uuid.uuid4())[:8],
            ticker=ticker,
            direction=direction,
            entry_price=round(entry, 2),
            stop_loss=sl,
            take_profit=tp,
            quantity=round(quantity, 4),
            risk_amount=round(risk_amount, 2),
            entry_time=datetime.now(timezone.utc).isoformat(),
            requested_entry_price=raw_entry,
            original_stop_loss=sl,
            original_quantity=round(quantity, 4),
        )
        self.positions.append(pos)
        return pos

    def check_fills(self, candle: dict) -> list[dict]:
        """Check if any open positions hit SL or TP based on a candle.

        Args:
            candle: Dict with high, low keys (from latest candle data)

        Returns:
            List of fill events (may include partial fills)
        """
        fills = []
        high = candle["high"]
        low = candle["low"]

        for pos in self.get_open_positions():
            if TRADE_MANAGEMENT_ENABLED and pos.original_stop_loss is not None:
                managed_fills = self._check_position_fill_managed(pos, high, low)
                fills.extend(managed_fills)
            else:
                fill = self._check_position_fill(pos, high, low)
                if fill:
                    fills.append(fill)

        return fills

    @staticmethod
    def _apply_slippage(fill_price: float, direction: str, fill_type: str) -> float:
        """Worsen fill price by slippage. SL/TP fills are always worse than ideal."""
        if SLIPPAGE_POINTS == 0:
            return fill_price
        if fill_type == "SL_HIT":
            # SL fills worsen: LONG SL fills lower, SHORT SL fills higher
            return fill_price - SLIPPAGE_POINTS if direction == "LONG" else fill_price + SLIPPAGE_POINTS
        else:  # TP_HIT
            # TP fills worsen: LONG TP fills lower, SHORT TP fills higher
            return fill_price - SLIPPAGE_POINTS if direction == "LONG" else fill_price + SLIPPAGE_POINTS

    def _check_position_fill_managed(self, pos: Position, high: float, low: float) -> list[dict]:
        """Staged trade management: partial close at 1R + breakeven, then trail.

        Returns a list of fill events (can be 0, 1, or 2 for partial + full).
        """
        fills = []
        risk = abs(pos.entry_price - pos.original_stop_loss) if pos.original_stop_loss else abs(pos.entry_price - pos.stop_loss)
        if risk == 0:
            return fills

        # Always check SL first (current SL, which may have been moved to BE)
        active_sl = pos.trailing_sl if pos.trailing_sl is not None else pos.stop_loss
        if pos.direction == "LONG":
            sl_hit = low <= active_sl
            tp_hit = high >= pos.take_profit
        else:
            sl_hit = high >= active_sl
            tp_hit = low <= pos.take_profit

        if sl_hit:
            price = self._apply_slippage(active_sl, pos.direction, "SL_HIT")
            reason = "TRAILING_SL" if pos.current_stage >= 1 else "SL_HIT"
            fills.append(self._close(pos, price, reason))
            return fills

        # Stage 0: Check if 1R profit reached → partial close 50% + move SL to BE
        if pos.current_stage == 0:
            target_1r = pos.entry_price + risk * BE_MOVE_THRESHOLD_R if pos.direction == "LONG" else pos.entry_price - risk * BE_MOVE_THRESHOLD_R
            hit_1r = (pos.direction == "LONG" and high >= target_1r) or (pos.direction == "SHORT" and low <= target_1r)

            if hit_1r:
                # Partial close
                partial_qty = math.floor(pos.original_quantity * PARTIAL_CLOSE_PCT)
                if partial_qty > 0 and partial_qty < pos.quantity:
                    partial_fill = self._partial_close(pos, target_1r, partial_qty, "PARTIAL_1R")
                    fills.append(partial_fill)

                # Move SL to breakeven
                pos.stop_loss = pos.entry_price
                pos.trailing_sl = pos.entry_price
                pos.current_stage = 1

        # Stage 1: trailing — SL trails behind price. TP check for full close.
        if pos.current_stage >= 1 and tp_hit:
            price = self._apply_slippage(pos.take_profit, pos.direction, "TP_HIT")
            fills.append(self._close(pos, price, "TP_HIT"))

        return fills

    def _partial_close(self, pos: Position, exit_price: float, quantity: float, reason: str) -> dict:
        """Close part of a position. Does NOT set status to CLOSED."""
        if pos.direction == "LONG":
            pnl = (exit_price - pos.entry_price) * quantity
        else:
            pnl = (pos.entry_price - exit_price) * quantity

        pos.quantity = round(pos.quantity - quantity, 4)
        partial = {
            "position_id": pos.id,
            "ticker": pos.ticker,
            "direction": pos.direction,
            "entry_price": pos.entry_price,
            "exit_price": round(exit_price, 2),
            "exit_reason": reason,
            "pnl_dollars": round(pnl, 2),
            "pnl_pct": round(pnl / (pos.entry_price * quantity) * 100, 2) if pos.entry_price else 0,
            "rr_achieved": calc_risk_reward(pos.entry_price, pos.original_stop_loss or pos.stop_loss, exit_price),
            "partial": True,
            "partial_quantity": round(quantity, 4),
        }
        pos.partial_fills.append(partial)
        return partial

    def update_trailing_sl(self, pos: Position, swing_levels: list[dict]):
        """Trail SL behind the nearest swing in profit direction.

        Only applies to positions in stage >= 1 (after partial close).
        """
        if pos.current_stage < 1 or not swing_levels:
            return

        if pos.direction == "LONG":
            # Trail behind swing lows (below price)
            valid_swings = [s["level"] for s in swing_levels
                           if s["type"] == "swing_low" and s["level"] < pos.entry_price + abs(pos.entry_price - (pos.original_stop_loss or pos.stop_loss))]
            if valid_swings:
                new_sl = max(valid_swings)
                if pos.trailing_sl is None or new_sl > pos.trailing_sl:
                    pos.trailing_sl = new_sl
                    pos.stop_loss = new_sl
        else:
            # Trail behind swing highs (above price)
            valid_swings = [s["level"] for s in swing_levels
                           if s["type"] == "swing_high" and s["level"] > pos.entry_price - abs(pos.entry_price - (pos.original_stop_loss or pos.stop_loss))]
            if valid_swings:
                new_sl = min(valid_swings)
                if pos.trailing_sl is None or new_sl < pos.trailing_sl:
                    pos.trailing_sl = new_sl
                    pos.stop_loss = new_sl

    def _check_position_fill(self, pos: Position, high: float, low: float) -> dict | None:
        """Check if a single position was filled by this candle's range."""
        if pos.direction == "LONG":
            if low <= pos.stop_loss:
                price = self._apply_slippage(pos.stop_loss, "LONG", "SL_HIT")
                return self._close(pos, price, "SL_HIT")
            if high >= pos.take_profit:
                price = self._apply_slippage(pos.take_profit, "LONG", "TP_HIT")
                return self._close(pos, price, "TP_HIT")
        else:  # SHORT
            if high >= pos.stop_loss:
                price = self._apply_slippage(pos.stop_loss, "SHORT", "SL_HIT")
                return self._close(pos, price, "SL_HIT")
            if low <= pos.take_profit:
                price = self._apply_slippage(pos.take_profit, "SHORT", "TP_HIT")
                return self._close(pos, price, "TP_HIT")
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
