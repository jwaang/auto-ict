"""MSS to the specification: body close past a swing, on a displacement candle.

The two things the library's detector gets wrong are exactly the two things
tested here — a wick poke must not register, and a break without displacement is
a CHoCH rather than an MSS.
"""
import pandas as pd
import pytest

from research.ict_mss import detect_mss, first_mss_after


def frame(closes, highs=None, lows=None):
    n = len(closes)
    return pd.DataFrame({
        "close": closes,
        "high": highs if highs is not None else [c + 1 for c in closes],
        "low": lows if lows is not None else [c - 1 for c in closes],
    })


def swing_high(level, idx):
    return {"type": "swing_high", "level": level, "candle_index": idx}


def swing_low(level, idx):
    return {"type": "swing_low", "level": level, "candle_index": idx}


class TestBodyCloseRequirement:
    def test_a_wick_poke_is_not_an_mss(self):
        """High pierces the swing but the close does not clear it."""
        closes = [100] * 12
        highs = [101] * 12
        highs[10] = 120           # wick well above the level
        bars = frame(closes, highs=highs)
        got = detect_mss(bars, [swing_high(110, 0)], {10}, confirm_lag=5)
        assert got == []

    def test_a_body_close_past_the_level_is_an_mss(self):
        closes = [100] * 12
        closes[10] = 115          # closes above the level
        bars = frame(closes)
        got = detect_mss(bars, [swing_high(110, 0)], {10}, confirm_lag=5)
        assert len(got) == 1
        assert got[0]["index"] == 10
        assert got[0]["direction"] == "bullish"

    def test_close_exactly_at_the_level_does_not_count(self):
        closes = [100] * 12
        closes[10] = 110
        bars = frame(closes)
        assert detect_mss(bars, [swing_high(110, 0)], {10}, confirm_lag=5) == []


class TestDisplacementRequirement:
    def test_break_without_displacement_is_a_choch_not_an_mss(self):
        closes = [100] * 12
        closes[10] = 115
        bars = frame(closes)
        # Bar 10 clears the level but is not a displacement bar.
        assert detect_mss(bars, [swing_high(110, 0)], set(), confirm_lag=5) == []

    def test_displacement_on_a_different_bar_does_not_rescue_it(self):
        closes = [100] * 12
        closes[10] = 115
        bars = frame(closes)
        assert detect_mss(bars, [swing_high(110, 0)], {7}, confirm_lag=5) == []


class TestDirection:
    def test_bearish_mss_breaks_a_swing_low_downward(self):
        closes = [100] * 12
        closes[10] = 85
        bars = frame(closes)
        got = detect_mss(bars, [swing_low(90, 0)], {10}, confirm_lag=5)
        assert len(got) == 1
        assert got[0]["direction"] == "bearish"

    def test_a_rise_does_not_break_a_swing_low(self):
        closes = [100] * 12
        closes[10] = 130
        bars = frame(closes)
        assert detect_mss(bars, [swing_low(90, 0)], {10}, confirm_lag=5) == []


class TestCausality:
    def test_a_break_before_the_confirmation_lag_is_ignored(self):
        """A swing is not known until its confirmation bar has printed."""
        closes = [100] * 12
        closes[3] = 115           # inside the lag window
        bars = frame(closes)
        assert detect_mss(bars, [swing_high(110, 0)], {3}, confirm_lag=5) == []

    def test_only_the_first_break_of_a_swing_is_reported(self):
        closes = [100] * 16
        closes[10] = 115
        closes[13] = 118
        bars = frame(closes)
        got = detect_mss(bars, [swing_high(110, 0)], {10, 13}, confirm_lag=5)
        assert [g["index"] for g in got] == [10]


class TestFirstMssAfter:
    def _mss(self, idx, direction):
        return {"index": idx, "direction": direction, "level": 1.0, "swing_index": 0}

    def test_finds_the_first_matching_shift_in_window(self):
        pool = [self._mss(5, "bearish"), self._mss(8, "bullish")]
        assert first_mss_after(pool, 3, "bullish", within=10)["index"] == 8

    def test_returns_none_when_past_the_window(self):
        pool = [self._mss(30, "bullish")]
        assert first_mss_after(pool, 3, "bullish", within=10) is None

    def test_ignores_shifts_at_or_before_the_anchor(self):
        pool = [self._mss(3, "bullish")]
        assert first_mss_after(pool, 3, "bullish", within=10) is None

    @pytest.mark.parametrize("want", ["bullish", "bearish"])
    def test_direction_must_match(self, want):
        other = "bearish" if want == "bullish" else "bullish"
        pool = [self._mss(5, other)]
        assert first_mss_after(pool, 1, want, within=10) is None
