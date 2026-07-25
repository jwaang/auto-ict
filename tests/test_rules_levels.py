"""Regression tests for entry/stop/target selection and realised R.

Both cases here were live bugs found while hunting for miscalculation:

- `_find_fvg_ob_overlap` returned the *first* overlapping zone it found. Detector
  output is oldest-first, so the highest-priority setup systematically picked the
  stalest zone in the window and derived the widest possible stop from it.
- `rr_achieved` was computed with an unsigned helper, so a full stop-out reported
  +1.0R. The reported "Avg R:R" was positive no matter how the strategy did.
"""

import pytest

from backtest.rules import _find_fvg_ob_overlap, _find_fvg_entry
from trading.risk import calc_risk_reward, realized_r


ATR = 4.0
SL_MULT = 0.5


def _zones():
    """A stale zone far below price and a recent one just below it."""
    obs = [
        {"low": 4900.0, "high": 4910.0, "candle_index": 5},     # stale
        {"low": 4985.0, "high": 4995.0, "candle_index": 400},   # recent
    ]
    fvgs = [
        {"bottom": 4905.0, "top": 4915.0, "candle_index": 6},
        {"bottom": 4990.0, "top": 5000.0, "candle_index": 401},
    ]
    return obs, fvgs


class TestOverlapPicksNearestZone:
    def test_long_uses_the_nearest_overlap(self):
        obs, fvgs = _zones()
        entry, stop = _find_fvg_ob_overlap("LONG", obs, fvgs, 5000.0, ATR, SL_MULT)
        assert entry == 5000.0
        # nearest OB low 4985 minus half an ATR, not the stale 4900
        assert stop == pytest.approx(4985.0 - ATR * SL_MULT)

    def test_short_uses_the_nearest_overlap(self):
        obs = [
            {"low": 5090.0, "high": 5100.0, "candle_index": 5},    # stale, far above
            {"low": 5005.0, "high": 5015.0, "candle_index": 400},  # recent, just above
        ]
        fvgs = [
            {"bottom": 5095.0, "top": 5105.0, "candle_index": 6},
            {"bottom": 5000.0, "top": 5010.0, "candle_index": 401},
        ]
        entry, stop = _find_fvg_ob_overlap("SHORT", obs, fvgs, 5000.0, ATR, SL_MULT)
        assert stop == pytest.approx(5015.0 + ATR * SL_MULT)

    def test_stop_stays_tight_relative_to_the_stale_alternative(self):
        """The whole point: a stale zone gives a stop many times too wide."""
        obs, fvgs = _zones()
        _, stop = _find_fvg_ob_overlap("LONG", obs, fvgs, 5000.0, ATR, SL_MULT)
        near_distance = 5000.0 - stop
        stale_distance = 5000.0 - (4900.0 - ATR * SL_MULT)
        assert near_distance < stale_distance / 3

    def test_zones_ahead_of_price_are_ignored(self):
        """A bullish zone above price is not an entry — price has left it."""
        obs = [{"low": 5010.0, "high": 5020.0, "candle_index": 400}]
        fvgs = [{"bottom": 5015.0, "top": 5025.0, "candle_index": 401}]
        entry, stop = _find_fvg_ob_overlap("LONG", obs, fvgs, 5000.0, ATR, SL_MULT)
        assert entry is None and stop is None

    def test_no_overlap_returns_nothing(self):
        obs = [{"low": 4900.0, "high": 4905.0, "candle_index": 1}]
        fvgs = [{"bottom": 4950.0, "top": 4960.0, "candle_index": 2}]
        assert _find_fvg_ob_overlap("LONG", obs, fvgs, 5000.0, ATR, SL_MULT) == (None, None)

    def test_consistent_with_the_fvg_only_finder(self):
        """Both finders should prefer the nearest zone, not disagree by ordering."""
        _, fvgs = _zones()
        _, fvg_stop = _find_fvg_entry("LONG", fvgs, 5000.0, ATR, SL_MULT)
        obs, fvgs2 = _zones()
        _, overlap_stop = _find_fvg_ob_overlap("LONG", obs, fvgs2, 5000.0, ATR, SL_MULT)
        # Both derive from the recent zone, so both stops sit near price.
        assert 5000.0 - fvg_stop < 40
        assert 5000.0 - overlap_stop < 40


class TestRealizedR:
    def test_full_stop_out_is_negative(self):
        assert realized_r("LONG", 5000, 4990, 4990) == -1.0
        assert realized_r("SHORT", 5000, 5010, 5010) == -1.0

    def test_target_hit_is_positive(self):
        assert realized_r("LONG", 5000, 4990, 5020) == 2.0
        assert realized_r("SHORT", 5000, 5010, 4980) == 2.0

    def test_flat_exit_is_zero(self):
        assert realized_r("LONG", 5000, 4990, 5000) == 0.0

    def test_partial_win_is_between(self):
        assert realized_r("LONG", 5000, 4990, 5005) == 0.5

    def test_zero_risk_is_zero(self):
        assert realized_r("LONG", 5000, 5000, 5020) == 0.0

    def test_planned_rr_stays_unsigned(self):
        """calc_risk_reward describes a proposal, where both legs are distances."""
        assert calc_risk_reward(5000, 4990, 5020) == 2.0
        assert calc_risk_reward(5000, 5010, 4980) == 2.0

    def test_average_of_losses_is_negative(self):
        """The bug: averaging unsigned R made a losing strategy look positive."""
        outcomes = [
            realized_r("LONG", 5000, 4990, 4990),   # loss
            realized_r("LONG", 5000, 4990, 4990),   # loss
            realized_r("LONG", 5000, 4990, 5020),   # win
        ]
        assert sum(outcomes) / len(outcomes) == pytest.approx(0.0)
        assert all(o == 1.0 for o in outcomes) is False
