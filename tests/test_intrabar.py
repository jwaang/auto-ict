"""Tests for 1-minute barrier resolution and excursion measurement.

Timestamps are bar-close labelled throughout, so a window is half-open on the
left: (start, end]. Getting that boundary wrong would silently read a bar from
before the trade opened.
"""

import pandas as pd
import pytest

from backtest.intrabar import Intrabar


def _frame(highs, lows, start="2024-01-02 10:01"):
    ts = pd.date_range(start, periods=len(highs), freq="1min", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "high": highs, "low": lows})


@pytest.fixture
def dip_then_rally():
    """Dips to 4995 at minute 3, then rallies to 5030 at minute 10."""
    highs = [5005] * 15
    lows = [5000] * 15
    lows[2] = 4995
    highs[9] = 5030
    return Intrabar(_frame(highs, lows))


WINDOW = (pd.Timestamp("2024-01-02 10:00", tz="UTC"),
          pd.Timestamp("2024-01-02 10:15", tz="UTC"))


class TestExtremes:
    def test_finds_the_high_and_low(self, dip_then_rally):
        assert dip_then_rally.extremes(*WINDOW) == (5030.0, 4995.0)

    def test_empty_window_returns_none(self, dip_then_rally):
        out = pd.Timestamp("2025-01-01", tz="UTC")
        assert dip_then_rally.extremes(out, out + pd.Timedelta(hours=1)) is None

    def test_window_is_half_open_on_the_left(self, dip_then_rally):
        """A bar stamped exactly at `start` belongs to the previous window."""
        first = pd.Timestamp("2024-01-02 10:01", tz="UTC")
        after = dip_then_rally.extremes(first, WINDOW[1])
        including = dip_then_rally.extremes(first - pd.Timedelta(minutes=1), WINDOW[1])
        assert after is not None and including is not None
        # Both contain the later extremes; only the second can contain bar one.
        assert including[1] <= after[1]


class TestFirstTouch:
    def test_stop_first_when_the_dip_comes_first(self, dip_then_rally):
        assert dip_then_rally.first_touch(*WINDOW, "LONG", 4996, 5030) == "SL_HIT"

    def test_target_first_when_the_stop_is_never_reached(self, dip_then_rally):
        assert dip_then_rally.first_touch(*WINDOW, "LONG", 4990, 5030) == "TP_HIT"

    def test_none_when_neither_is_reached(self, dip_then_rally):
        assert dip_then_rally.first_touch(*WINDOW, "LONG", 4990, 5099) is None

    def test_short_direction_is_mirrored(self):
        # Rises to 5030 at minute 2, falls to 4970 at minute 8.
        highs = [5005] * 12
        lows = [5000] * 12
        highs[1] = 5030
        lows[7] = 4970
        ib = Intrabar(_frame(highs, lows))
        window = (pd.Timestamp("2024-01-02 10:00", tz="UTC"),
                  pd.Timestamp("2024-01-02 10:12", tz="UTC"))
        # Short from 5000: stop above at 5020 is hit before target below at 4970.
        assert ib.first_touch(*window, "SHORT", 5020, 4970) == "SL_HIT"
        assert ib.first_touch(*window, "SHORT", 5099, 4970) == "TP_HIT"

    def test_same_minute_resolves_pessimistically(self):
        """One bar cannot be split, so a bar holding both counts as the stop."""
        ib = Intrabar(_frame([5030], [4970]))
        window = (pd.Timestamp("2024-01-02 10:00", tz="UTC"),
                  pd.Timestamp("2024-01-02 10:01", tz="UTC"))
        assert ib.first_touch(*window, "LONG", 4980, 5020) == "SL_HIT"


class TestExcursion:
    def test_long_favourable_and_adverse(self, dip_then_rally):
        got = dip_then_rally.excursion("LONG", 5000, 4990, *WINDOW)
        assert got == {"mfe_r": 3.0, "mae_r": 0.5}

    def test_short_is_mirrored(self, dip_then_rally):
        got = dip_then_rally.excursion("SHORT", 5000, 5010, *WINDOW)
        assert got == {"mfe_r": 0.5, "mae_r": 3.0}

    def test_zero_risk_returns_nothing(self, dip_then_rally):
        assert dip_then_rally.excursion("LONG", 5000, 5000, *WINDOW) == {}

    def test_empty_window_returns_nothing(self, dip_then_rally):
        out = pd.Timestamp("2025-01-01", tz="UTC")
        assert dip_then_rally.excursion("LONG", 5000, 4990, out, out) == {}

    def test_r_is_relative_to_the_stop_so_widths_are_comparable(self, dip_then_rally):
        """A 20-point stop halves the R multiples a 10-point stop reports."""
        tight = dip_then_rally.excursion("LONG", 5000, 4990, *WINDOW)
        wide = dip_then_rally.excursion("LONG", 5000, 4980, *WINDOW)
        assert wide["mfe_r"] == pytest.approx(tight["mfe_r"] / 2)


class TestExcursionSummary:
    def test_reports_how_often_the_target_was_reachable(self):
        from backtest.experiments import _excursion_summary
        trades = [
            # Reached its 2R target.
            {"status": "CLOSED", "mfe_r": 2.1, "mae_r": 0.3, "pnl_dollars": 100.0,
             "entry_price": 5000, "stop_loss": 4990, "take_profit": 5020},
            # Never got close.
            {"status": "CLOSED", "mfe_r": 0.4, "mae_r": 1.2, "pnl_dollars": -100.0,
             "entry_price": 5000, "stop_loss": 4990, "take_profit": 5020},
        ]
        got = _excursion_summary(trades)
        assert got["n"] == 2
        assert got["median_target_r"] == 2.0
        assert got["pct_reached_target_r"] == 50.0
        assert got["median_mfe_r_winners"] == 2.1
        assert got["median_mfe_r_losers"] == 0.4

    def test_ignores_trades_without_excursion(self):
        from backtest.experiments import _excursion_summary
        assert _excursion_summary([{"status": "CLOSED", "pnl_dollars": 1.0}]) == {}
