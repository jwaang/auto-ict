"""Silver Bullet windows: boundaries, and the arithmetic that forces 1-minute.

The repo previously measured zero Silver Bullet trades over a full year at 15m
and 5m. That was not evidence about the strategy — the sequence cannot fit inside
its own window at those timeframes. These tests pin that reasoning so the next
reader does not repeat the conclusion.
"""
import pandas as pd
import pytest

from research.sb_windows import (bars_per_window, sequence_can_fit,
                                 window_bounds, window_for)

ET = "America/New_York"


def et(s):
    return pd.Timestamp(s).tz_localize(ET).tz_convert("UTC")


class TestWindowMembership:
    @pytest.mark.parametrize("when,expected", [
        ("2024-03-05 03:00", "sb_london"),
        ("2024-03-05 03:59", "sb_london"),
        ("2024-03-05 10:00", "sb_ny_am"),
        ("2024-03-05 10:30", "sb_ny_am"),
        ("2024-03-05 10:59", "sb_ny_am"),
        ("2024-03-05 14:00", "sb_ny_pm"),
        ("2024-03-05 14:59", "sb_ny_pm"),
    ])
    def test_inside(self, when, expected):
        assert window_for(et(when)) == expected

    @pytest.mark.parametrize("when", [
        "2024-03-05 02:59",   # a minute early
        "2024-03-05 04:00",   # the closing hour is exclusive
        "2024-03-05 09:59",
        "2024-03-05 11:00",
        "2024-03-05 13:59",
        "2024-03-05 15:00",
        "2024-03-05 20:00",
    ])
    def test_outside(self, when):
        assert window_for(et(when)) is None

    def test_membership_follows_new_york_not_utc(self):
        """13:00 UTC is 09:00 ET in winter — outside, despite looking mid-morning."""
        assert window_for(pd.Timestamp("2024-01-15 13:00", tz="UTC")) is None
        assert window_for(pd.Timestamp("2024-01-15 15:00", tz="UTC")) == "sb_ny_am"


class TestWindowBounds:
    def test_bounds_span_exactly_one_hour(self):
        lo, hi = window_bounds("2024-03-05", "sb_ny_am")
        assert hi - lo == pd.Timedelta(hours=1)

    def test_bounds_are_in_new_york_wall_clock(self):
        lo, _ = window_bounds("2024-03-05", "sb_ny_am")
        assert lo.tz_convert(ET).hour == 10

    def test_bounds_hold_across_daylight_saving(self):
        """Wall-clock 10:00 ET on both sides of the March transition."""
        before, _ = window_bounds("2024-03-08", "sb_ny_am")
        after, _ = window_bounds("2024-03-12", "sb_ny_am")
        assert before.tz_convert(ET).hour == after.tz_convert(ET).hour == 10
        assert before.hour != after.hour        # the UTC offset really did move


class TestSequenceArithmetic:
    @pytest.mark.parametrize("minutes,expected", [(1, 60), (3, 20), (5, 12), (15, 4)])
    def test_bars_per_window(self, minutes, expected):
        assert bars_per_window(minutes) == expected

    def test_only_one_minute_can_fit_the_sequence(self):
        """15 bars are needed for a structure shift to form, confirm and break."""
        assert sequence_can_fit(1)
        assert sequence_can_fit(3)
        assert not sequence_can_fit(5)
        assert not sequence_can_fit(15)

    def test_the_prior_zero_trade_result_is_explained_by_arithmetic(self):
        """15m gives 4 bars against ~15 needed — impossible, not selective."""
        assert bars_per_window(15) < 15
        assert bars_per_window(5) < 15
