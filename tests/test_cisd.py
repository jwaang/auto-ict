"""Tests for Change In State of Delivery detection.

CISD earns its place by being causally clean: it reads closed candle bodies against
an opening price that was known before the signal bar opened. Order blocks are
defined retroactively ("the last down candle before the up move"), so the causality
tests here are the point of the module, not an afterthought.
"""

import pandas as pd
import pytest

from ict.cisd import detect_cisd, latest_cisd


def _bar(open_, close, high=None, low=None):
    return {
        "open": open_, "close": close,
        "high": high if high is not None else max(open_, close) + 1,
        "low": low if low is not None else min(open_, close) - 1,
    }


def _frame(bars):
    df = pd.DataFrame(bars)
    df["timestamp"] = pd.date_range("2024-01-02", periods=len(df), freq="15min", tz="UTC")
    return df


DOWN_RUN_THEN_BREAK = [
    _bar(5010, 5005),   # 0 down — run starts, reference is its OPEN of 5010
    _bar(5005, 4998),   # 1 down
    _bar(4998, 4990, low=4989),  # 2 down, run low 4989
    _bar(4990, 5002),   # 3 up but closes below 5010, not yet a CISD
    _bar(5002, 5012),   # 4 up and closes above 5010 -> bullish CISD
]


class TestBullishDetection:
    def test_fires_on_the_close_through_the_reference(self):
        events = detect_cisd(_frame(DOWN_RUN_THEN_BREAK))
        assert len(events) == 1
        event = events[0]
        assert event["type"] == "bullish"
        assert event["candle_index"] == 4
        assert event["reference"] == 5010.0
        assert event["run_extreme"] == 4989.0

    def test_reference_is_the_first_candle_of_the_run(self):
        """Not the last, and not the run's low — where the sellers began."""
        events = detect_cisd(_frame(DOWN_RUN_THEN_BREAK))
        assert events[0]["reference"] == DOWN_RUN_THEN_BREAK[0]["open"]

    def test_a_wick_through_is_not_a_cisd(self):
        """ICT is explicit: bodies only. A high above the reference does not count."""
        bars = DOWN_RUN_THEN_BREAK[:3] + [
            _bar(4990, 5001, high=5050),   # wick way above 5010, body closes below
        ]
        assert detect_cisd(_frame(bars)) == []

    def test_no_signal_without_a_break(self):
        bars = DOWN_RUN_THEN_BREAK[:3] + [_bar(4990, 4995), _bar(4995, 5000)]
        assert detect_cisd(_frame(bars)) == []


class TestBearishDetection:
    def test_mirrors_the_bullish_case(self):
        bars = [
            _bar(4990, 4995),            # up — run starts, reference 4990
            _bar(4995, 5002),            # up
            _bar(5002, 5010, high=5011), # up, run high 5011
            _bar(5010, 4998),            # closes below 4990? no, 4998 > 4990
            _bar(4998, 4985),            # closes below 4990 -> bearish CISD
        ]
        events = detect_cisd(_frame(bars))
        assert len(events) == 1
        assert events[0]["type"] == "bearish"
        assert events[0]["candle_index"] == 4
        assert events[0]["reference"] == 4990.0
        assert events[0]["run_extreme"] == 5011.0


class TestCausality:
    """A signal must never appear at a bar once later bars are appended."""

    @staticmethod
    def _keyed(events):
        return {(e["candle_index"], e["type"]) for e in events}

    def test_appending_bars_creates_no_past_signal(self):
        bars = DOWN_RUN_THEN_BREAK + [
            _bar(5012, 5006), _bar(5006, 5001), _bar(5001, 5020),
            _bar(5020, 5014), _bar(5014, 5030),
        ]
        for cut in range(4, len(bars)):
            early = self._keyed(detect_cisd(_frame(bars[:cut])))
            later = self._keyed(detect_cisd(_frame(bars)))
            created = {k for k in later if k[0] < cut} - early
            assert not created, (
                f"signal appeared at {created} only after bars beyond {cut} existed"
            )

    def test_signal_index_is_never_before_the_run_ends(self):
        events = detect_cisd(_frame(DOWN_RUN_THEN_BREAK))
        for event in events:
            assert event["candle_index"] > event["run_end"]

    def test_run_bounds_precede_the_signal(self):
        events = detect_cisd(_frame(DOWN_RUN_THEN_BREAK))
        for event in events:
            assert event["run_start"] <= event["run_end"] < event["candle_index"]


class TestStaleness:
    def test_a_run_ages_out(self):
        """Without a bound, a run from long ago fires on an unrelated move — the
        same staleness problem the FVG+OB overlap finder had."""
        bars = DOWN_RUN_THEN_BREAK[:3]
        bars += [_bar(4990, 4991) for _ in range(40)]   # drift, never breaks 5010
        bars.append(_bar(4991, 5020))                    # break, but far too late
        assert detect_cisd(_frame(bars), max_run_age=30) == []
        assert detect_cisd(_frame(bars), max_run_age=100) != []

    def test_short_frames_are_safe(self):
        assert detect_cisd(_frame([_bar(5000, 5001)])) == []
        assert detect_cisd(pd.DataFrame()) == []


class TestLatestCisd:
    @pytest.fixture
    def events(self):
        return detect_cisd(_frame(DOWN_RUN_THEN_BREAK))

    def test_returns_a_fresh_matching_event(self, events):
        got = latest_cisd(events, "LONG", current_index=6, max_age=10)
        assert got is not None and got["candle_index"] == 4

    def test_rejects_a_stale_event(self, events):
        assert latest_cisd(events, "LONG", current_index=40, max_age=10) is None

    def test_direction_must_match(self, events):
        assert latest_cisd(events, "SHORT", current_index=6, max_age=10) is None

    def test_ignores_events_after_the_current_bar(self, events):
        """A backtest at bar 2 must not see a signal from bar 4."""
        assert latest_cisd(events, "LONG", current_index=2, max_age=10) is None

    def test_empty_list_is_safe(self):
        assert latest_cisd([], "LONG", current_index=10) is None
