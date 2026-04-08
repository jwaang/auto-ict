"""Tests for trading modules: account, positions, risk validation."""

import pytest

from trading.account import Account
from trading.positions import PositionManager
from trading.risk import validate_trade, calc_risk_reward


class TestAccount:
    def test_initial_balance(self):
        acc = Account(starting_balance=100_000)
        assert acc.balance == 100_000
        assert acc.peak_balance == 100_000

    def test_risk_amount(self):
        acc = Account(starting_balance=100_000)
        assert acc.get_risk_amount() == 1000  # 1% default

    def test_position_size(self):
        acc = Account(starting_balance=100_000)
        # 1% risk = $1000, SL distance = $10 → 100 units
        size = acc.get_position_size(entry=100, stop_loss=90)
        assert size == 100.0

    def test_update_balance(self):
        acc = Account(starting_balance=100_000)
        acc.update_balance(500)
        assert acc.balance == 100_500
        assert acc.peak_balance == 100_500

    def test_drawdown(self):
        acc = Account(starting_balance=100_000)
        acc.update_balance(-5000)
        assert acc.get_drawdown_pct() == 5.0

    def test_circuit_breaker(self):
        acc = Account(starting_balance=100_000)
        acc.update_balance(-10_000)  # 10% drawdown
        assert acc.is_circuit_breaker_hit()

    def test_no_circuit_breaker_under_threshold(self):
        acc = Account(starting_balance=100_000)
        acc.update_balance(-9_000)  # 9%
        assert not acc.is_circuit_breaker_hit()


class TestPositionManager:
    def test_open_and_close_long(self):
        acc = Account(starting_balance=100_000)
        pm = PositionManager()
        decision = {
            "decision": "LONG",
            "entry_price": 5000,
            "stop_loss": 4950,
            "take_profit": 5150,
        }
        pos = pm.open_position(decision, acc, "ES")
        assert pos.direction == "LONG"
        assert pos.status == "OPEN"
        assert pm.get_open_count() == 1

        # TP hit
        fills = pm.check_fills({"high": 5200, "low": 4980})
        assert len(fills) == 1
        assert fills[0]["exit_reason"] == "TP_HIT"
        assert fills[0]["pnl_dollars"] > 0
        assert pm.get_open_count() == 0

    def test_sl_hit_short(self):
        acc = Account(starting_balance=100_000)
        pm = PositionManager()
        decision = {
            "decision": "SHORT",
            "entry_price": 5000,
            "stop_loss": 5050,
            "take_profit": 4850,
        }
        pos = pm.open_position(decision, acc, "ES")

        fills = pm.check_fills({"high": 5060, "low": 4990})
        assert len(fills) == 1
        assert fills[0]["exit_reason"] == "SL_HIT"
        assert fills[0]["pnl_dollars"] < 0


class TestRiskValidation:
    def test_valid_long_trade(self):
        acc = Account(starting_balance=100_000)
        decision = {
            "decision": "LONG",
            "entry_price": 5000,
            "stop_loss": 4950,
            "take_profit": 5150,
        }
        valid, reason = validate_trade(decision, acc, 0)
        assert valid, reason

    def test_reject_bad_rr(self):
        acc = Account(starting_balance=100_000)
        decision = {
            "decision": "LONG",
            "entry_price": 5000,
            "stop_loss": 4950,
            "take_profit": 5030,  # R:R = 0.6
        }
        valid, reason = validate_trade(decision, acc, 0)
        assert not valid
        assert "R:R" in reason

    def test_reject_wrong_sl_direction(self):
        acc = Account(starting_balance=100_000)
        decision = {
            "decision": "LONG",
            "entry_price": 5000,
            "stop_loss": 5050,  # SL above entry for LONG
            "take_profit": 5200,
        }
        valid, reason = validate_trade(decision, acc, 0)
        assert not valid

    def test_reject_max_positions(self):
        acc = Account(starting_balance=100_000)
        decision = {
            "decision": "LONG",
            "entry_price": 5000,
            "stop_loss": 4950,
            "take_profit": 5150,
        }
        valid, reason = validate_trade(decision, acc, 3)  # Already at max
        assert not valid
        assert "Max concurrent" in reason

    def test_calc_risk_reward(self):
        assert calc_risk_reward(100, 90, 130) == 3.0
        assert calc_risk_reward(100, 90, 120) == 2.0
        assert calc_risk_reward(100, 90, 100) == 0.0  # Entry = TP
