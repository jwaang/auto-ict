"""Account management — balance tracking, position sizing, equity history."""

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from config import MAX_DRAWDOWN_PCT, RISK_PER_TRADE_PCT


@dataclass
class Account:
    starting_balance: float
    balance: float = 0.0
    peak_balance: float = 0.0
    equity_history: list[dict] = field(default_factory=list)
    circuit_breaker_triggered: bool = False
    # Mark-to-market tracking, updated once per bar by the backtest engine.
    current_equity: float | None = None
    peak_equity: float = 0.0
    max_drawdown_pct: float = 0.0
    # Drawdown limit for the latching circuit breaker. Overridable so a research
    # run can measure a whole span instead of stopping at the first drawdown —
    # left at the default, a 12-month backtest reported 2 months.
    drawdown_limit_pct: float = MAX_DRAWDOWN_PCT

    def __post_init__(self):
        if self.balance == 0.0:
            self.balance = self.starting_balance
        if self.peak_balance == 0.0:
            self.peak_balance = self.balance
        if not self.equity_history:
            self.equity_history.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "balance": self.balance,
                "event": "init",
            })

    def get_risk_amount(self, risk_pct: float | None = None) -> float:
        """Calculate dollar amount to risk per trade."""
        pct = risk_pct if risk_pct is not None else RISK_PER_TRADE_PCT
        return self.balance * pct / 100

    def get_position_size(
        self,
        entry: float,
        stop_loss: float,
        risk_pct: float | None = None,
        point_value: float = 1.0,
        whole_units: bool = False,
    ) -> float:
        """Calculate position size to risk exactly risk_pct of account.

        Args:
            entry: Entry price
            stop_loss: Stop price
            risk_pct: Override for the account risk percentage
            point_value: Dollars per point per contract (1.0 for stocks/crypto)
            whole_units: Round down to whole contracts. Futures cannot be
                traded fractionally, so a wide stop can size to 0 — the caller
                must treat that as "no trade".

        Returns:
            Number of units or contracts (fractional unless whole_units).
        """
        risk_amount = self.get_risk_amount(risk_pct)
        sl_distance = abs(entry - stop_loss)
        if sl_distance == 0:
            return 0.0
        size = risk_amount / (sl_distance * point_value)
        return float(math.floor(size)) if whole_units else size

    def update_balance(self, pnl: float, event: str = "trade_close"):
        """Update balance after a trade closes."""
        self.balance += pnl
        self.peak_balance = max(self.peak_balance, self.balance)
        self.equity_history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "balance": round(self.balance, 2),
            "pnl": round(pnl, 2),
            "event": event,
        })

    def mark_equity(self, equity: float):
        """Record mark-to-market equity and update the peak and worst drawdown.

        Balance alone only moves when a trade closes, so it hides the drawdown
        an open losing position is already carrying.
        """
        self.current_equity = equity
        self.peak_equity = max(self.peak_equity or self.starting_balance, equity)
        if self.peak_equity > 0:
            drawdown = (self.peak_equity - equity) / self.peak_equity * 100
            self.max_drawdown_pct = max(self.max_drawdown_pct, drawdown)

    def is_circuit_breaker_hit(self) -> bool:
        """Check if drawdown from peak exceeds MAX_DRAWDOWN_PCT or was already triggered."""
        if self.circuit_breaker_triggered:
            return True
        equity = self.current_equity if self.current_equity is not None else self.balance
        peak = max(self.peak_balance, self.peak_equity)
        if peak == 0:
            return False
        drawdown_pct = (peak - equity) / peak * 100
        return drawdown_pct >= self.drawdown_limit_pct

    def trigger_circuit_breaker(self):
        """Latch the circuit breaker — halts all trading for the session."""
        self.circuit_breaker_triggered = True

    def get_drawdown_pct(self) -> float:
        """Current drawdown percentage from peak."""
        if self.peak_balance == 0:
            return 0.0
        return round((self.peak_balance - self.balance) / self.peak_balance * 100, 2)

    def snapshot(self) -> dict:
        """Current account state for logging/prompt."""
        return {
            "balance": round(self.balance, 2),
            "starting_balance": self.starting_balance,
            "peak_balance": round(self.peak_balance, 2),
            "drawdown_pct": self.get_drawdown_pct(),
            "circuit_breaker": self.is_circuit_breaker_hit(),
            "open_position_count": 0,  # Updated by PositionManager
        }
