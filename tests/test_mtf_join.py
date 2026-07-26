"""The context-to-execution join must never look ahead.

A 15-minute bar stamped 10:15 completes at 10:15, so reacting to it may only use
execution bars strictly after that instant. Selecting the 10:15 execution bar
itself would let the strategy respond to a close using a bar that printed before
that close existed.
"""
import pandas as pd
import pytest

from research.mtf_join import first_execution_bar_after, window_bounds


@pytest.fixture
def minutes():
    """Ten one-minute bars, 10:10 through 10:19 inclusive."""
    return pd.date_range("2024-03-05 10:10", periods=10, freq="1min")


class TestFirstExecutionBarAfter:
    def test_bar_at_the_context_close_is_excluded(self, minutes):
        """10:15 exists in the series and must not be chosen for a 10:15 close."""
        got = first_execution_bar_after(minutes, pd.Timestamp("2024-03-05 10:15"))
        assert minutes[got] == pd.Timestamp("2024-03-05 10:16")

    def test_picks_the_next_bar_when_close_falls_between_bars(self, minutes):
        got = first_execution_bar_after(minutes, pd.Timestamp("2024-03-05 10:15:30"))
        assert minutes[got] == pd.Timestamp("2024-03-05 10:16")

    def test_context_close_before_all_data_gives_the_first_bar(self, minutes):
        got = first_execution_bar_after(minutes, pd.Timestamp("2024-03-05 09:00"))
        assert got == 0

    def test_context_close_at_or_past_the_end_returns_none(self, minutes):
        assert first_execution_bar_after(minutes, pd.Timestamp("2024-03-05 10:19")) is None
        assert first_execution_bar_after(minutes, pd.Timestamp("2024-03-05 11:00")) is None


class TestWindowBounds:
    def test_window_starts_after_the_close_and_covers_the_span(self, minutes):
        start, end = window_bounds(minutes, pd.Timestamp("2024-03-05 10:12"), minutes=3)
        assert minutes[start] == pd.Timestamp("2024-03-05 10:13")
        # 3 minutes from 10:12 reaches 10:15 inclusive, so end is exclusive of 10:16.
        assert minutes[end - 1] == pd.Timestamp("2024-03-05 10:15")

    def test_zero_length_window_is_empty_not_negative(self, minutes):
        start, end = window_bounds(minutes, pd.Timestamp("2024-03-05 10:12"), minutes=0)
        assert end >= start

    def test_no_execution_data_after_the_close(self, minutes):
        assert window_bounds(minutes, pd.Timestamp("2024-03-05 12:00"), 30) == (None, None)

    def test_every_selected_bar_is_strictly_after_the_close(self, minutes):
        close = pd.Timestamp("2024-03-05 10:13")
        start, end = window_bounds(minutes, close, minutes=5)
        assert all(t > close for t in minutes[start:end])
