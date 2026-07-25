"""Position lifecycle — open, monitor, close paper trades."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import math

from config import (
    BE_MOVE_THRESHOLD_R,
    COMMISSION_PER_CONTRACT,
    PARTIAL_CLOSE_PCT,
    SLIPPAGE_POINTS,
    SPREAD_POINTS,
    TRADE_MANAGEMENT_ENABLED,
    get_point_value,
    is_futures,
)
from trading.account import Account
from trading.risk import realized_r


def fill_penalty() -> float:
    """Points a single fill gives up to the market.

    A market order crosses half the spread and then slips. Both legs of a round
    trip pay it, so a round turn costs `SPREAD_POINTS + 2 * SLIPPAGE_POINTS`.
    """
    return SPREAD_POINTS / 2 + SLIPPAGE_POINTS


def _worsen(price: float, direction: str, side: str) -> float:
    """Move a fill price against the position by one fill penalty.

    `side` is "entry" or "exit". A long buys higher and sells lower; a short is
    the mirror. There is no case where a fill lands in your favour.
    """
    penalty = fill_penalty()
    if penalty == 0:
        return price
    paying_up = (direction == "LONG") if side == "entry" else (direction != "LONG")
    return price + penalty if paying_up else price - penalty


def _gross_pnl(pos: "Position", exit_price: float, quantity: float) -> float:
    """P&L before commission, in dollars.

    Spread and slippage are already inside `pos.entry_price` and `exit_price`,
    since both are recorded net of the fill penalty.
    """
    move = exit_price - pos.entry_price if pos.direction == "LONG" else pos.entry_price - exit_price
    return move * quantity * pos.point_value


def _commission(pos: "Position", quantity: float) -> float:
    """Round-turn commission for the quantity being closed."""
    if not is_futures(pos.ticker):
        return 0.0
    return COMMISSION_PER_CONTRACT * quantity


def _costs(pos: "Position", quantity: float) -> float:
    """Everything the round trip pays away: spread, slippage and commission.

    Reported separately from P&L so "costs ate the edge" is a measurement rather
    than an inference — the absence of this is why the first attempt at that
    claim was wrong.
    """
    slip = fill_penalty() * 2 * quantity * pos.point_value
    return slip + _commission(pos, quantity)


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
    point_value: float = 1.0  # Dollars per point per contract
    # Trade management fields
    original_stop_loss: float | None = None
    original_quantity: float = 0.0
    partial_fills: list = field(default_factory=list)
    current_stage: int = 0   # 0=initial, 1=partial taken + trailing
    trailing_sl: float | None = None


class PositionManager:
    def __init__(self):
        self.positions: list[Position] = []

    def open_position(self, decision: dict, account: Account, ticker: str) -> Position | None:
        """Open a new paper trade position.

        Args:
            decision: AI trade decision dict with entry/SL/TP
            account: Account for position sizing
            ticker: Ticker symbol

        Returns:
            New Position, or None when the stop is too wide to afford a single
            contract at the configured risk.
        """
        raw_entry = decision["entry_price"]
        sl = decision["stop_loss"]
        tp = decision["take_profit"]
        direction = decision["decision"]

        # The entry fill gives up half the spread plus slippage. The exit leg
        # pays the same again in _apply_slippage — charging only one of the two
        # under-stated a round turn by half.
        entry = _worsen(raw_entry, direction, "entry")

        # Futures trade in whole contracts at a fixed dollar value per point.
        point_value = get_point_value(ticker)
        quantity = account.get_position_size(
            entry, sl, point_value=point_value, whole_units=is_futures(ticker)
        )
        if quantity <= 0:
            return None

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
            point_value=point_value,
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
    def _apply_slippage(fill_price: float, direction: str, fill_type: str = "") -> float:
        """Worsen an exit fill by half the spread plus slippage.

        `fill_type` is kept for call-site readability; SL and TP fills are
        penalised identically, which is what the two former branches already did
        with duplicate expressions.
        """
        return _worsen(fill_price, direction, "exit")

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
                    # A partial exit crosses the spread like any other fill.
                    price = self._apply_slippage(target_1r, pos.direction, "PARTIAL_1R")
                    partial_fill = self._partial_close(pos, price, partial_qty, "PARTIAL_1R")
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
        pnl = _gross_pnl(pos, exit_price, quantity) - _commission(pos, quantity)
        costs = _costs(pos, quantity)
        notional = pos.entry_price * quantity * pos.point_value

        pos.quantity = round(pos.quantity - quantity, 4)
        partial = {
            "position_id": pos.id,
            "ticker": pos.ticker,
            "direction": pos.direction,
            "entry_price": pos.entry_price,
            "exit_price": round(exit_price, 2),
            "exit_reason": reason,
            "pnl_dollars": round(pnl, 2),
            "pnl_pct": round(pnl / notional * 100, 2) if notional else 0,
            "gross_pnl": round(pnl + costs, 2),
            "costs": round(costs, 2),
            "rr_achieved": realized_r(pos.direction, pos.entry_price, pos.original_stop_loss or pos.stop_loss, exit_price),
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
        """Close a position and calculate P&L.

        `pnl` is what the account receives. `costs` is what the round trip paid
        away, and `gross_pnl` is what it would have made at the unpenalised
        levels — so `gross_pnl - costs == pnl` holds exactly, because the spread
        and slippage are already inside entry_price and exit_price.
        """
        pnl = _gross_pnl(pos, exit_price, pos.quantity) - _commission(pos, pos.quantity)
        costs = _costs(pos, pos.quantity)
        gross = pnl + costs

        notional = pos.entry_price * pos.quantity * pos.point_value

        pos.status = "CLOSED"
        pos.exit_price = exit_price
        pos.exit_reason = reason
        pos.exit_time = datetime.now(timezone.utc).isoformat()
        pos.pnl_dollars = round(pnl, 2)
        pos.pnl_pct = round(pnl / notional * 100, 2) if notional else 0

        return {
            "position_id": pos.id,
            "ticker": pos.ticker,
            "direction": pos.direction,
            "entry_price": pos.entry_price,
            "exit_price": exit_price,
            "exit_reason": reason,
            "pnl_dollars": pos.pnl_dollars,
            "pnl_pct": pos.pnl_pct,
            "gross_pnl": round(gross, 2),
            "costs": round(costs, 2),
            "rr_achieved": realized_r(pos.direction, pos.entry_price, pos.stop_loss, exit_price),
        }

    def close_position_manual(self, position_id: str, exit_price: float,
                              reason: str = "MANUAL") -> dict | None:
        """Close a position at a given price, paying the usual exit costs.

        The engine uses this for session-end, circuit-breaker and end-of-backtest
        closes — 19% of exits on a measured year. It used to bypass the fill
        penalty entirely, so nearly a fifth of round trips were free.
        """
        for pos in self.positions:
            if pos.id == position_id and pos.status == "OPEN":
                price = self._apply_slippage(exit_price, pos.direction, reason)
                return self._close(pos, price, reason)
        return None

    def unrealized_pnl(self, price: float) -> float:
        """Mark-to-market P&L of every open position at the given price."""
        return sum(_gross_pnl(pos, price, pos.quantity) for pos in self.get_open_positions())

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
