"""Tests for per-run parameter overrides.

A leak between cells would silently corrupt a whole sweep — every row after the
leak would report the wrong config — so the isolation properties are worth
asserting directly rather than trusting.
"""

import pytest

from backtest import params


class TestOverrideBasics:
    def test_get_returns_default_when_unset(self):
        assert params.get("nothing_set_here", 7) == 7

    def test_override_visible_inside_block(self):
        with params.overrides({"min_rr_ratio": 1.25}):
            assert params.get("min_rr_ratio", 2.0) == 1.25

    def test_override_cleared_after_block(self):
        with params.overrides({"min_rr_ratio": 1.25}):
            pass
        assert params.get("min_rr_ratio", 2.0) == 2.0

    def test_none_and_empty_clear(self):
        params.set_overrides({"a": 1})
        params.set_overrides(None)
        assert params.get("a", "default") == "default"
        params.set_overrides({"a": 1})
        params.set_overrides({})
        assert params.get("a", "default") == "default"

    def test_none_is_a_real_value_not_a_miss(self):
        """tp_fallback_r=None means 'no fallback target', so it must not read as
        unset and fall back to the config default."""
        with params.overrides({"tp_fallback_r": None}):
            assert params.get("tp_fallback_r", 3.0) is None


class TestIsolation:
    def test_sequential_cells_do_not_leak(self):
        for value in (1.0, 1.5, 2.0):
            with params.overrides({"min_rr_ratio": value}):
                assert params.get("min_rr_ratio", 99) == value
            assert params.get("min_rr_ratio", 99) == 99

    def test_nested_restores_outer(self):
        with params.overrides({"a": "outer"}):
            with params.overrides({"a": "inner"}):
                assert params.get("a", None) == "inner"
            assert params.get("a", None) == "outer"
        assert params.get("a", "gone") == "gone"

    def test_restores_after_exception(self):
        with pytest.raises(RuntimeError):
            with params.overrides({"min_rr_ratio": 1.0}):
                raise RuntimeError("boom")
        assert params.get("min_rr_ratio", 2.0) == 2.0

    def test_active_snapshot_is_a_copy(self):
        with params.overrides({"a": 1}):
            snap = params.active()
            snap["a"] = 999
            assert params.get("a", None) == 1

    def test_caller_dict_is_copied(self):
        """Mutating the dict passed in must not change live overrides."""
        source = {"a": 1}
        with params.overrides(source):
            source["a"] = 999
            assert params.get("a", None) == 1


class TestConsumersReadAtCallTime:
    """The whole point is that consumers do not bind the value at import."""

    def test_risk_and_rules_share_one_rr_override(self):
        """MIN_RR_RATIO is enforced in both modules. If either still reads the
        import-time constant, a sweep of it silently does nothing."""
        from trading.account import Account
        from trading.risk import validate_trade

        account = Account(starting_balance=100_000)
        # 10-point stop, 15-point target on MES -> R:R 1.5, under the 2.0 default
        decision = {
            "decision": "LONG", "entry_price": 5000.0,
            "stop_loss": 4990.0, "take_profit": 5015.0,
        }
        ok, reason = validate_trade(decision, account, 0, ticker="MES")
        assert not ok and "R:R" in reason

        with params.overrides({"min_rr_ratio": 1.0}):
            ok, reason = validate_trade(decision, account, 0, ticker="MES")
        assert ok, f"override ignored by trading.risk: {reason}"

    def test_drawdown_limit_override(self):
        from trading.account import Account
        tight = Account(starting_balance=100_000)
        tight.update_balance(-10_500)
        assert tight.is_circuit_breaker_hit()

        loose = Account(starting_balance=100_000, drawdown_limit_pct=100.0)
        loose.update_balance(-10_500)
        assert not loose.is_circuit_breaker_hit()

    def test_bias_vote_rule_override_changes_result(self):
        """Only structure votes, bullish, and the other three abstain.

        The default rule needs 3 aligned, and the tie-break only fires on an
        actual tie, so a lone 1-0 vote returns neutral. That strictness is what
        the sweep exists to test — plurality takes the same input as bullish.
        """
        from ict.confluence import determine_ict_bias
        bias = {"bias": "bullish", "premium_discount": {"zone": "neutral"}}
        swing = {"bias": "neutral", "premium_discount": {"zone": "neutral"}}
        entry = {"previous_high_low": {}, "liquidity_zones": [], "current_price": 5000}

        assert determine_ict_bias(bias, swing, entry) == "neutral"

        with params.overrides({"bias_vote_rule": "plurality"}):
            assert determine_ict_bias(bias, swing, entry) == "bullish"

        with params.overrides({"bias_min_votes": 1}):
            assert determine_ict_bias(bias, swing, entry) == "bullish"


class TestRaidFactor:
    """The raid factor abstained on every bar because it asked whether a side had
    ever been swept in the window rather than which was swept most recently."""

    @staticmethod
    def _ctx(zones):
        return (
            {"bias": "neutral", "premium_discount": {"zone": "neutral"}},
            {"bias": "neutral", "premium_discount": {"zone": "neutral"}},
            {"previous_high_low": {}, "liquidity_zones": zones, "current_price": 5000},
        )

    def test_votes_when_both_sides_swept(self):
        from ict.confluence import bias_factors
        zones = [
            {"type": "sell_side", "swept": True, "sweep_candle_index": 90},
            {"type": "buy_side", "swept": True, "sweep_candle_index": 40},
        ]
        assert bias_factors(*self._ctx(zones))["raid"] == "bullish"

        zones[0]["sweep_candle_index"] = 10
        assert bias_factors(*self._ctx(zones))["raid"] == "bearish"

    def test_abstains_only_when_nothing_swept(self):
        from ict.confluence import bias_factors
        zones = [{"type": "sell_side", "swept": False, "sweep_candle_index": None}]
        assert bias_factors(*self._ctx(zones))["raid"] is None
