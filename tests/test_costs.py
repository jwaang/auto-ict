"""Tests for the transaction cost model.

These exist because the first attempt at "costs ate the edge" was wrong: the
engine recorded only net P&L, so the claim was inferred from arithmetic instead of
measured, and three defects went unnoticed — the exit leg never paid the spread,
manual closes paid nothing at all, and nothing was recorded.
"""

import math

import pytest

import config
from trading.account import Account
from trading.positions import PositionManager, fill_penalty


ROUND_TRIP_POINTS = config.SPREAD_POINTS + 2 * config.SLIPPAGE_POINTS
MES_POINT_VALUE = 5.0


def _long(entry=5000.0, stop=4990.0, target=5020.0):
    return {"decision": "LONG", "entry_price": entry,
            "stop_loss": stop, "take_profit": target}


class TestFillPenalty:
    def test_each_fill_pays_half_spread_plus_slippage(self):
        assert fill_penalty() == pytest.approx(
            config.SPREAD_POINTS / 2 + config.SLIPPAGE_POINTS
        )

    def test_entry_fill_is_worse_than_requested(self):
        pm = PositionManager()
        pos = pm.open_position(_long(), Account(starting_balance=100_000), "MES")
        assert pos.entry_price > pos.requested_entry_price, "long must buy higher"

    def test_short_entry_fill_is_worse_than_requested(self):
        pm = PositionManager()
        decision = {"decision": "SHORT", "entry_price": 5000.0,
                    "stop_loss": 5010.0, "take_profit": 4980.0}
        pos = pm.open_position(decision, Account(starting_balance=100_000), "MES")
        assert pos.entry_price < pos.requested_entry_price, "short must sell lower"


class TestRoundTripCost:
    @staticmethod
    def _close_at(reason):
        """Open one MES long and close it, returning the fill."""
        pm = PositionManager()
        pos = pm.open_position(_long(), Account(starting_balance=100_000), "MES")
        if reason == "TP_HIT":
            fills = pm.check_fills({"high": 5100.0, "low": 4995.0})
            return pos, fills[0]
        if reason == "SL_HIT":
            fills = pm.check_fills({"high": 5005.0, "low": 4900.0})
            return pos, fills[0]
        return pos, pm.close_position_manual(pos.id, 5005.0, reason)

    @pytest.mark.parametrize("reason", ["TP_HIT", "SL_HIT", "SESSION_END", "BACKTEST_END"])
    def test_cost_matches_the_documented_model(self, reason):
        """Every exit path pays the same round trip, including manual closes.

        Manual closes used to bypass the fill penalty entirely, and they are 19%
        of exits on a measured year.
        """
        pos, fill = self._close_at(reason)
        qty = pos.original_quantity
        expected = (
            ROUND_TRIP_POINTS * qty * MES_POINT_VALUE
            + config.COMMISSION_PER_CONTRACT * qty
        )
        assert fill["costs"] == pytest.approx(expected, abs=0.01)

    def test_session_end_costs_the_same_as_a_tp(self):
        _, tp = self._close_at("TP_HIT")
        _, se = self._close_at("SESSION_END")
        assert tp["costs"] == pytest.approx(se["costs"])

    @pytest.mark.parametrize("reason", ["TP_HIT", "SL_HIT", "SESSION_END"])
    def test_gross_minus_costs_equals_net(self, reason):
        _, fill = self._close_at(reason)
        assert fill["gross_pnl"] - fill["costs"] == pytest.approx(
            fill["pnl_dollars"], abs=0.01
        )

    def test_costs_scale_with_contracts(self):
        """Cost per contract is fixed, so cost drag as a share of R is
        size-invariant — which is why the published ~1.02/stop_points holds."""
        pm = PositionManager()
        small = pm.open_position(_long(), Account(starting_balance=100_000), "MES")
        big = pm.open_position(_long(), Account(starting_balance=1_000_000), "MES")
        assert big.quantity > small.quantity
        fills = pm.check_fills({"high": 5100.0, "low": 4995.0})
        by_qty = {round(f["costs"] / q, 4)
                  for f, q in zip(fills, (small.original_quantity, big.original_quantity))}
        assert len(by_qty) == 1, "cost per contract must not depend on size"


class TestCostsCanBeDisabled:
    def test_zero_costs_makes_gross_equal_net(self, monkeypatch):
        monkeypatch.setattr(config, "SPREAD_POINTS", 0.0)
        monkeypatch.setattr(config, "SLIPPAGE_POINTS", 0.0)
        monkeypatch.setattr(config, "COMMISSION_PER_CONTRACT", 0.0)
        import trading.positions as positions
        monkeypatch.setattr(positions, "SPREAD_POINTS", 0.0)
        monkeypatch.setattr(positions, "SLIPPAGE_POINTS", 0.0)
        monkeypatch.setattr(positions, "COMMISSION_PER_CONTRACT", 0.0)

        pm = PositionManager()
        pos = pm.open_position(_long(), Account(starting_balance=100_000), "MES")
        assert pos.entry_price == pos.requested_entry_price
        fill = pm.check_fills({"high": 5100.0, "low": 4995.0})[0]
        assert fill["costs"] == 0
        assert fill["gross_pnl"] == pytest.approx(fill["pnl_dollars"])


class TestStatsReportCosts:
    def test_calc_stats_sums_costs_and_buckets_exit_reasons(self):
        from backtest.engine import BacktestResult
        from backtest.report import calc_stats

        result = BacktestResult(starting_balance=100_000, final_balance=100_150)
        result.trades = [
            {"status": "CLOSED", "pnl_dollars": 200.0, "gross_pnl": 260.0,
             "costs": 60.0, "exit_reason": "TP_HIT", "rr_achieved": 2.0},
            {"status": "CLOSED", "pnl_dollars": -50.0, "gross_pnl": 10.0,
             "costs": 60.0, "exit_reason": "SESSION_END", "rr_achieved": 0.1},
        ]
        stats = calc_stats(result)
        assert stats["total_costs"] == 120.0
        assert stats["gross_pnl"] == 270.0
        assert stats["cost_per_trade"] == 60.0
        assert stats["exit_reasons"]["TP_HIT"]["n"] == 1
        assert stats["exit_reasons"]["SESSION_END"]["win_rate"] == 0.0

    def test_no_trades_still_reports_cost_keys(self):
        from backtest.engine import BacktestResult
        from backtest.report import calc_stats
        stats = calc_stats(BacktestResult(starting_balance=100_000))
        assert stats["total_costs"] == 0.0
        assert stats["exit_reasons"] == {}
