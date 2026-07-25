"""Tests for the barrier-only benchmark comparison.

The random-walk benchmark stop/(stop+target) is a first-passage result for two
absorbing barriers. It describes a trade that ends at its stop or its target and
nothing else. Session-end and circuit-breaker closes end at whatever price is
there, so including them compares a mixed population against a null built for a
subset — and because forced closes skew to small winners, doing so inflates the
apparent edge. These tests pin the population down.
"""

import math

import pytest

from backtest.experiments import (
    _edge,
    _geometry,
    barrier_from_exit_reasons,
)


def _trade(reason, pnl, entry=5000.0, stop=4990.0, target=5020.0):
    return {
        "status": "CLOSED", "exit_reason": reason, "pnl_dollars": pnl,
        "entry_price": entry, "stop_loss": stop, "take_profit": target,
    }


# 10-point stop, 20-point target -> benchmark 10/30 = 33.3%
TP = _trade("TP_HIT", 1000.0)
SL = _trade("SL_HIT", -500.0)
SESSION = _trade("SESSION_END", 40.0)


class TestPopulation:
    def test_only_barrier_exits_reach_the_benchmark(self):
        got = _geometry([TP, SL, SESSION])
        assert got["barrier_n"] == 2
        assert got["nonbarrier_n"] == 1
        assert got["barrier_win_rate"] == 50.0

    def test_forced_closes_do_not_inflate_the_edge(self):
        """Nine small session-end winners must not turn a coin flip into an edge."""
        trades = [TP, SL] + [_trade("SESSION_END", 40.0)] * 9
        got = _geometry(trades)
        assert got["barrier_win_rate"] == 50.0
        assert got["nonbarrier_n"] == 9
        # The old metric would have read 10 wins in 11 trades, or 90.9%.
        assert got["barrier_edge"] == pytest.approx(50.0 - 33.3, abs=0.1)

    def test_their_pnl_is_reported_rather_than_dropped(self):
        got = _geometry([TP, SL, _trade("SESSION_END", 40.0),
                         _trade("CIRCUIT_BREAKER", -25.0)])
        assert got["nonbarrier_n"] == 2
        assert got["nonbarrier_pnl"] == 15.0

    def test_benchmark_uses_barrier_geometry_only(self):
        """A wide-target session-end trade must not move the benchmark."""
        wide = _trade("SESSION_END", 10.0, target=5100.0)
        assert _geometry([TP, SL, wide])["coinflip_win_rate"] == pytest.approx(33.3, abs=0.1)

    def test_no_barrier_exits_still_reports_the_rest(self):
        got = _geometry([SESSION])
        assert got["barrier_n"] == 0
        assert got["nonbarrier_n"] == 1
        assert "barrier_edge" not in got


class TestEdgeStatistic:
    def test_edge_is_observed_minus_benchmark_in_points(self):
        assert _edge(wins=50, n=100, coinflip=1 / 3)["barrier_edge"] == pytest.approx(16.7, abs=0.1)

    def test_z_scales_with_sample_size(self):
        """The same edge on 4x the trades is twice as many standard errors."""
        small = _edge(wins=10, n=20, coinflip=1 / 3)["barrier_z"]
        large = _edge(wins=40, n=80, coinflip=1 / 3)["barrier_z"]
        assert large == pytest.approx(small * 2, rel=0.02)

    def test_z_matches_the_binomial_standard_error(self):
        p = 1 / 3
        expected = (0.5 - p) / math.sqrt(p * (1 - p) / 100)
        assert _edge(wins=50, n=100, coinflip=p)["barrier_z"] == pytest.approx(expected, abs=0.01)

    def test_matching_the_benchmark_is_zero_edge(self):
        got = _edge(wins=33, n=99, coinflip=1 / 3)
        assert got["barrier_edge"] == 0.0
        assert got["barrier_z"] == 0.0

    def test_empty_sample_is_safe(self):
        assert _edge(wins=0, n=0, coinflip=1 / 3) == {}


class TestBackfillFromHistory:
    """Old rows predate the fix but stored per-exit-reason counts, so the
    corrected figure is derivable without re-running anything."""

    EXITS = {
        "SL_HIT": {"n": 33, "wins": 0, "net_pnl": -29388.0, "win_rate": 0.0},
        "TP_HIT": {"n": 17, "wins": 17, "net_pnl": 28079.0, "win_rate": 100.0},
        "SESSION_END": {"n": 8, "wins": 8, "net_pnl": 2200.0, "win_rate": 100.0},
    }

    def test_recovers_the_barrier_win_rate(self):
        got = barrier_from_exit_reasons(self.EXITS, coinflip=28.2)
        assert got["barrier_n"] == 50
        assert got["barrier_win_rate"] == 34.0

    def test_recovers_a_negative_edge_the_old_metric_showed_positive(self):
        """This row published +14.9 on a 43.1% overall win rate. Barrier-only it
        is +5.8, and pooled with its siblings the sign flips."""
        got = barrier_from_exit_reasons(self.EXITS, coinflip=28.2)
        assert got["barrier_edge"] == pytest.approx(5.8, abs=0.1)

    def test_separates_the_forced_closes(self):
        got = barrier_from_exit_reasons(self.EXITS, coinflip=28.2)
        assert got["nonbarrier_n"] == 8
        assert got["nonbarrier_pnl"] == 2200.0

    def test_missing_coinflip_yields_counts_without_an_edge(self):
        got = barrier_from_exit_reasons(self.EXITS, coinflip=None)
        assert got["barrier_win_rate"] == 34.0
        assert "barrier_edge" not in got

    def test_empty_history_is_safe(self):
        assert barrier_from_exit_reasons({}, coinflip=28.2) == {}
