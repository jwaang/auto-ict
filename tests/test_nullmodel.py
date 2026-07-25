"""Tests for the empirical null.

The point of the null is to be honest about time censoring, so the tests that
matter most are the ones pinning the cutoff and confirming that a random entry
on a driftless series lands near the analytic rate when nothing is censored, and
below it when the cutoff bites.
"""

import numpy as np
import pandas as pd
import pytest

from backtest.nullmodel import geometry_from_trades, run_null_model, session_end


class TestSessionEnd:
    def test_cutoff_is_1600_et_the_same_day(self):
        # 14:30 ET = 18:30 UTC in summer.
        entry = pd.Timestamp("2024-06-03 18:30", tz="UTC")
        assert session_end(entry) == pd.Timestamp("2024-06-03 20:00", tz="UTC")

    def test_an_entry_after_the_cutoff_belongs_to_the_next_session(self):
        entry = pd.Timestamp("2024-06-03 21:00", tz="UTC")  # 17:00 ET
        assert session_end(entry) == pd.Timestamp("2024-06-04 20:00", tz="UTC")

    def test_an_entry_exactly_at_the_cutoff_rolls_forward(self):
        entry = pd.Timestamp("2024-06-03 20:00", tz="UTC")  # 16:00 ET
        assert session_end(entry) == pd.Timestamp("2024-06-04 20:00", tz="UTC")

    def test_the_cutoff_tracks_daylight_saving(self):
        """16:00 ET is 21:00 UTC in winter and 20:00 UTC in summer."""
        winter = session_end(pd.Timestamp("2024-01-10 15:00", tz="UTC"))
        summer = session_end(pd.Timestamp("2024-07-10 15:00", tz="UTC"))
        assert winter.hour == 21
        assert summer.hour == 20


def _walk(n_minutes, seed=0, step=0.25, start="2024-06-03 09:30"):
    """A driftless random walk sampled as 1-minute bars."""
    rng = np.random.default_rng(seed)
    moves = rng.choice([-step, step], size=n_minutes).cumsum()
    close = 5000.0 + moves
    ts = pd.date_range(start, periods=n_minutes, freq="1min", tz="America/New_York")
    return pd.DataFrame({
        "timestamp": ts.tz_convert("UTC"),
        "high": close + step, "low": close - step, "close": close,
    })


class TestNullModel:
    def test_a_driftless_walk_lands_near_the_analytic_rate(self):
        """With a 2:1 target and room to resolve, roughly a third should win.

        This is the calibration check: if the machinery is right, an uncensored
        driftless walk reproduces stop/(stop+target).
        """
        df = _walk(6000, start="2024-06-03 00:00")
        entries = pd.DatetimeIndex(df["timestamp"][::15][:60])
        got = run_null_model(df, entries, np.array([2.0]), np.array([2.0]),
                             n=800, seed=1)
        assert got["null_barrier_n"] > 400
        assert got["null_win_rate"] == pytest.approx(33.3, abs=6.0)

    def test_censoring_pushes_the_win_rate_below_the_analytic_rate(self):
        """The whole reason this module exists.

        A far target needs more time than a near stop, so a cutoff removes
        target-hits more often — the measured rate must sit below the formula.
        """
        df = _walk(6000, start="2024-06-03 00:00")
        entries = pd.DatetimeIndex(df["timestamp"][::15][:60])
        wide = run_null_model(df, entries, np.array([12.0]), np.array([3.0]),
                              n=800, seed=2)
        assert wide["null_censored_pct"] > 20
        assert wide["null_win_rate"] < wide["analytic_win_rate"]

    def test_the_same_seed_gives_the_same_answer(self):
        df = _walk(3000, start="2024-06-03 00:00")
        entries = pd.DatetimeIndex(df["timestamp"][::15][:40])
        args = (df, entries, np.array([3.0]), np.array([2.0]))
        assert run_null_model(*args, n=200, seed=7) == run_null_model(*args, n=200, seed=7)

    def test_geometry_is_sampled_from_what_was_passed_in(self):
        df = _walk(3000, start="2024-06-03 00:00")
        entries = pd.DatetimeIndex(df["timestamp"][::15][:40])
        got = run_null_model(df, entries, np.array([8.0]), np.array([2.5]),
                             n=100, seed=3)
        assert got["median_stop_pts"] == 8.0
        assert got["median_target_mult"] == 2.5

    def test_empty_inputs_are_safe(self):
        df = _walk(100)
        assert run_null_model(df, pd.DatetimeIndex([]), np.array([1.0]),
                              np.array([2.0])) == {}
        assert run_null_model(df, pd.DatetimeIndex(df["timestamp"][:5]),
                              np.array([]), np.array([])) == {}


class TestGeometryFromTrades:
    def test_reads_stops_and_multiples(self):
        trades = [{
            "status": "CLOSED", "entry_price": 5000.0,
            "stop_loss": 4990.0, "take_profit": 5020.0,
        }]
        stops, mults = geometry_from_trades(trades)
        assert stops.tolist() == [10.0]
        assert mults.tolist() == [2.0]

    def test_skips_open_trades_and_zero_stops(self):
        trades = [
            {"status": "OPEN", "entry_price": 5000.0, "stop_loss": 4990.0,
             "take_profit": 5020.0},
            {"status": "CLOSED", "entry_price": 5000.0, "stop_loss": 5000.0,
             "take_profit": 5020.0},
        ]
        stops, _ = geometry_from_trades(trades)
        assert len(stops) == 0
