"""The FVG strength classifier, on hand-built candles.

`candle_index` points at the third candle of the pattern, so every fixture here
lays out four bars — prior, candle 1, candle 2, candle 3 — and the FVG record
indexes the last one.
"""
import numpy as np
import pytest

from research.fvg_quality import (EXCEPTIONAL, QUIETLY_STRONG, WEAK,
                                  classify_all, classify_fvg)


def build(bars):
    """bars is a list of (high, low); returns arrays and an index for candle 3."""
    high = np.array([b[0] for b in bars], dtype=float)
    low = np.array([b[1] for b in bars], dtype=float)
    return high, low, len(bars) - 1


def fvg(idx, kind="bullish"):
    return {"candle_index": idx, "type": kind}


class TestBullish:
    def test_weak_when_displacement_stays_inside_the_prior_range(self):
        """Candle 2 never exceeds the prior candle's high — a trap."""
        high, low, i = build([(120, 80), (100, 90), (110, 95), (115, 100)])
        assert classify_fvg(fvg(i), high, low) == WEAK

    def test_quietly_strong_when_candle_three_does_not_extend(self):
        """Candle 2 breaks out; candle 3 fails to make a new high."""
        high, low, i = build([(100, 90), (99, 92), (115, 98), (112, 105)])
        assert classify_fvg(fvg(i), high, low) == QUIETLY_STRONG

    def test_exceptional_when_candle_three_extends_beyond_candle_two(self):
        high, low, i = build([(100, 90), (99, 92), (115, 98), (125, 112)])
        assert classify_fvg(fvg(i), high, low) == EXCEPTIONAL

    def test_equal_high_does_not_count_as_a_break(self):
        """A touch is not a break; the comparison is strict."""
        high, low, i = build([(100, 90), (99, 92), (100, 95), (105, 99)])
        assert classify_fvg(fvg(i), high, low) == WEAK


class TestBearish:
    def test_weak(self):
        high, low, i = build([(120, 80), (110, 95), (105, 85), (100, 82)])
        assert classify_fvg(fvg(i, "bearish"), high, low) == WEAK

    def test_quietly_strong(self):
        high, low, i = build([(110, 100), (108, 101), (102, 85), (95, 88)])
        assert classify_fvg(fvg(i, "bearish"), high, low) == QUIETLY_STRONG

    def test_exceptional(self):
        high, low, i = build([(110, 100), (108, 101), (102, 85), (90, 75)])
        assert classify_fvg(fvg(i, "bearish"), high, low) == EXCEPTIONAL


class TestGuards:
    @pytest.mark.parametrize("idx", [0, 1, 2])
    def test_too_early_to_judge(self, idx):
        """Needs a bar before candle 1, so the first three bars are unjudgeable."""
        high, low, _ = build([(100, 90)] * 6)
        assert classify_fvg(fvg(idx), high, low) is None

    def test_index_past_the_frame(self):
        high, low, _ = build([(100, 90)] * 4)
        assert classify_fvg(fvg(99), high, low) is None

    def test_missing_index(self):
        high, low, _ = build([(100, 90)] * 4)
        assert classify_fvg({"type": "bullish"}, high, low) is None

    def test_classify_all_partitions_every_input(self):
        high, low, i = build([(100, 90), (99, 92), (115, 98), (125, 112)])
        got = classify_all([fvg(i), fvg(0), fvg(i, "bearish")], high, low)
        assert len(got[EXCEPTIONAL]) == 1
        assert len(got["skipped"]) == 1
        assert sum(len(v) for v in got.values()) == 3
