"""Account management — balance tracking, position sizing, equity history."""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from config import MAX_DRAWDOWN_PCT, RISK_PER_TRADE_PCT


@dataclass
class Account:
    starting_balance: float
    balance: float = 0.0
    peak_balance: float = 0.0
    equity_history: list[dict] = field(default_factory=list)

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

    def get_position_size(self, entry: float, stop_loss: float, risk_pct: float | None = None) -> float:
        """Calculate position size (shares/units) to risk exactly risk_pct of account.

        Returns number of units (can be fractional for crypto).
        """
        risk_amount = self.get_risk_amount(risk_pct)
        sl_distance = abs(entry - stop_loss)
        if sl_distance == 0:
            return 0.0
        return risk_amount / sl_distance

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

    def is_circuit_breaker_hit(self) -> bool:
        """Check if drawdown from peak exceeds MAX_DRAWDOWN_PCT."""
        if self.peak_balance == 0:
            return False
        drawdown_pct = (self.peak_balance - self.balance) / self.peak_balance * 100
        return drawdown_pct >= MAX_DRAWDOWN_PCT

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
