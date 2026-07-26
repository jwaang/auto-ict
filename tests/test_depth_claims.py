"""Retracement depth binning, and the first-touch causality it depends on.

The causality is the point. Three look-ahead defects in this programme came from
measuring where price ended up rather than where it first reached, and every one
of them made the result look better than reality.
"""
import numpy as np
import pytest

from research.depth_claims import (band_for, first_touch_by_band,
                                   retracement_depth)


class TestRetracementDepth:
    def test_at_the_leg_extreme_depth_is_zero(self):
        assert retracement_depth(110, 100, 110) == pytest.approx(0.0)

    def test_back_at_the_origin_depth_is_one(self):
        assert retracement_depth(100, 100, 110) == pytest.approx(1.0)

    def test_halfway_back_is_one_half(self):
        assert retracement_depth(105, 100, 110) == pytest.approx(0.5)

    def test_beyond_the_origin_exceeds_one(self):
        assert retracement_depth(95, 100, 110) == pytest.approx(1.5)

    def test_bearish_leg_mirrors(self):
        """A high-to-low leg retraces upward; depth still runs 0 to 1."""
        assert retracement_depth(90, 110, 90) == pytest.approx(0.0)
        assert retracement_depth(110, 110, 90) == pytest.approx(1.0)
        assert retracement_depth(100, 110, 90) == pytest.approx(0.5)

    def test_zero_range_leg_is_not_a_number(self):
        assert retracement_depth(100, 100, 100) != retracement_depth(100, 100, 100)


class TestBandBoundaries:
    @pytest.mark.parametrize("depth,expected", [
        (0.0, "<38.2"),
        (0.30, "<38.2"),
        (0.382, "38.2-61.8"),      # boundary belongs to the deeper band
        (0.50, "38.2-61.8"),
        (0.618, "61.8-79 OTE"),    # the OTE band opens exactly at 61.8
        (0.705, "61.8-79 OTE"),    # the stated sweet spot
        (0.789, "61.8-79 OTE"),
        (0.79, "79-100"),          # and closes exactly at 79
        (0.95, "79-100"),
        (1.0, ">100 invalid"),
        (1.5, ">100 invalid"),
    ])
    def test_boundaries(self, depth, expected):
        assert band_for(depth) == expected

    def test_negative_depth_has_no_band(self):
        """Price beyond the leg extreme is extension, not retracement."""
        assert band_for(-0.1) is None

    def test_nan_has_no_band(self):
        assert band_for(float("nan")) is None


class TestFirstTouchCausality:
    def _series(self, lows):
        highs = [x + 1 for x in lows]
        return np.array(highs, dtype=float), np.array(lows, dtype=float)

    def test_records_the_bar_a_band_is_first_reached(self):
        # Leg 100 -> 110. Lows walk back: 110, 106 (40%), 102 (80%).
        high, low = self._series([110, 110, 106, 102])
        got = first_touch_by_band(high, low, 100, 110, from_idx=0, limit=10, n=4)
        assert got["38.2-61.8"] == 2
        assert got["79-100"] == 3

    def test_nothing_is_measured_before_the_confirmation_bar(self):
        """A deep retracement before confirmation must not be counted."""
        high, low = self._series([102, 110, 110, 110])   # bar 0 is deep, pre-confirm
        got = first_touch_by_band(high, low, 100, 110, from_idx=0, limit=10, n=4)
        assert "79-100" not in got

    def test_a_band_is_recorded_once_at_its_first_touch(self):
        high, low = self._series([110, 104, 103, 104])   # 60%, 70%, 60%
        got = first_touch_by_band(high, low, 100, 110, from_idx=0, limit=10, n=4)
        assert got["38.2-61.8"] == 1

    def test_one_retracement_can_populate_several_bands(self):
        """Correct: at 62% nobody knew whether it would stop or run to 85%."""
        high, low = self._series([110, 106, 103, 101])
        got = first_touch_by_band(high, low, 100, 110, from_idx=0, limit=10, n=4)
        assert set(got) >= {"38.2-61.8", "61.8-79 OTE", "79-100"}

    def test_tracking_stops_once_the_leg_is_invalidated(self):
        high, low = self._series([110, 99, 104])         # bar 1 breaks the origin
        got = first_touch_by_band(high, low, 100, 110, from_idx=0, limit=10, n=3)
        assert got[">100 invalid"] == 1
        assert "38.2-61.8" not in got                    # never revisited after

    def test_limit_bounds_the_search(self):
        high, low = self._series([110, 110, 110, 102])
        got = first_touch_by_band(high, low, 100, 110, from_idx=0, limit=2, n=4)
        assert "79-100" not in got

    def test_bearish_leg_uses_highs(self):
        """Retracing a high-to-low leg means price rising, so highs matter."""
        lows = [90, 96, 90, 90]
        high = np.array([90, 97, 90, 90], dtype=float)
        low = np.array(lows, dtype=float)
        got = first_touch_by_band(high, low, 110, 90, from_idx=0, limit=10, n=4)
        assert got["<38.2"] == 1                          # 97 is 35% back up


class TestGapDepth:
    def test_bullish_gap_near_edge_is_the_top(self):
        """A bullish gap sits below price, so price enters from the top."""
        from research.depth_claims import gap_depth
        assert gap_depth(110, top=110, bottom=100, bullish=True) == pytest.approx(0.0)
        assert gap_depth(105, top=110, bottom=100, bullish=True) == pytest.approx(0.5)
        assert gap_depth(100, top=110, bottom=100, bullish=True) == pytest.approx(1.0)

    def test_bearish_gap_near_edge_is_the_bottom(self):
        from research.depth_claims import gap_depth
        assert gap_depth(100, top=110, bottom=100, bullish=False) == pytest.approx(0.0)
        assert gap_depth(105, top=110, bottom=100, bullish=False) == pytest.approx(0.5)
        assert gap_depth(110, top=110, bottom=100, bullish=False) == pytest.approx(1.0)

    def test_beyond_the_far_edge_exceeds_one(self):
        from research.depth_claims import gap_depth
        assert gap_depth(95, top=110, bottom=100, bullish=True) == pytest.approx(1.5)

    def test_zero_width_gap_is_not_a_number(self):
        from research.depth_claims import gap_depth
        d = gap_depth(100, top=100, bottom=100, bullish=True)
        assert d != d


class TestGapFirstTouch:
    def _bars(self, lows):
        return (np.array([x + 0.0 for x in lows]), np.array(lows, dtype=float))

    def test_records_each_level_at_first_touch(self):
        from research.depth_claims import first_touch_by_level
        # Gap 100-110 bullish. Lows: 110 (0%), 105 (50%), 101 (90%).
        high, low = self._bars([115, 110, 105, 101])
        got = first_touch_by_level(high, low, 110, 100, True, from_idx=0, limit=10, n=4)
        assert got["near edge"] == 1
        assert got["CE 50%"] == 2
        assert got["75%"] == 3

    def test_nothing_before_the_third_candle(self):
        """The gap is not knowable until its third candle closes."""
        from research.depth_claims import first_touch_by_level
        high, low = self._bars([100, 115, 115, 115])   # bar 0 is deep, pre-gap
        got = first_touch_by_level(high, low, 110, 100, True, from_idx=0, limit=10, n=4)
        assert got == {}

    def test_a_single_bar_can_register_several_levels(self):
        from research.depth_claims import first_touch_by_level
        high, low = self._bars([115, 102])
        got = first_touch_by_level(high, low, 110, 100, True, from_idx=0, limit=10, n=2)
        assert {"near edge", "25%", "CE 50%", "75%"} <= set(got)

    def test_stops_once_fully_mitigated(self):
        from research.depth_claims import first_touch_by_level
        high, low = self._bars([115, 95, 105])
        got = first_touch_by_level(high, low, 110, 100, True, from_idx=0, limit=10, n=3)
        assert got["mitigated"] == 1
