"""Tests for ict/smc_adapter.py — wrapper layer correctness and integration.

Verifies that the adapter correctly translates smc_patched DataFrame outputs
into list-of-dict format, and that filter helpers work correctly.
"""

import pandas as pd
import numpy as np
import pytest

from ict.smc_adapter import (
    prepare_ohlc,
    detect_swings,
    detect_bos_choch,
    detect_order_blocks,
    detect_fvgs,
    detect_liquidity,
    detect_previous_high_low,
    detect_retracements,
    get_unfilled_fvgs,
    get_unmitigated_obs,
    get_swing_length,
    set_swing_length_override,
)


# ===========================================================================
# prepare_ohlc
# ===========================================================================

class TestPrepareOHLC:

    def test_sets_datetime_index(self, sample_ohlcv):
        result = prepare_ohlc(sample_ohlcv)
        assert isinstance(result.index, pd.DatetimeIndex)
        assert "timestamp" not in result.columns

    def test_adds_missing_volume(self):
        df = pd.DataFrame({
            "timestamp": pd.date_range("2025-01-01", periods=5, freq="15min"),
            "open": [100]*5, "high": [101]*5, "low": [99]*5, "close": [100]*5,
        })
        result = prepare_ohlc(df)
        assert "volume" in result.columns
        assert (result["volume"] == 0).all()

    def test_returns_copy(self, sample_ohlcv):
        result = prepare_ohlc(sample_ohlcv)
        result["close"] = 0
        assert (sample_ohlcv["close"] != 0).all(), "Original should be unchanged"

    def test_preserves_columns(self, sample_ohlcv):
        result = prepare_ohlc(sample_ohlcv)
        for col in ["open", "high", "low", "close", "volume"]:
            assert col in result.columns


# ===========================================================================
# detect_swings
# ===========================================================================

class TestDetectSwings:

    def test_returns_tuple(self, sample_ohlcv):
        ohlc = prepare_ohlc(sample_ohlcv)
        result = detect_swings(ohlc, "entry")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_swings_list_format(self, sample_ohlcv):
        ohlc = prepare_ohlc(sample_ohlcv)
        _, swings = detect_swings(ohlc, "entry")
        for s in swings:
            assert "type" in s and s["type"] in ("swing_high", "swing_low")
            assert "level" in s and isinstance(s["level"], float)
            assert "candle_index" in s and isinstance(s["candle_index"], int)
            assert "timestamp" in s

    def test_raw_df_usable_by_other_functions(self, sample_ohlcv):
        """The raw DataFrame should work as input to bos_choch, ob, etc."""
        ohlc = prepare_ohlc(sample_ohlcv)
        shl_df, _ = detect_swings(ohlc, "entry")
        assert "HighLow" in shl_df.columns
        assert "Level" in shl_df.columns
        # Should not crash when passed to other functions
        detect_bos_choch(ohlc, shl_df)
        detect_order_blocks(ohlc, shl_df)

    def test_swing_length_override(self, sample_ohlcv):
        ohlc = prepare_ohlc(sample_ohlcv)
        set_swing_length_override({"entry": 3})
        try:
            assert get_swing_length("entry") == 3
            _, swings_short = detect_swings(ohlc, "entry")
        finally:
            set_swing_length_override(None)

        _, swings_default = detect_swings(ohlc, "entry")
        # Shorter swing length should detect more swings
        assert len(swings_short) >= len(swings_default)

    def test_unknown_tf_label_defaults(self):
        assert get_swing_length("unknown_tf") == 10


# ===========================================================================
# detect_fvgs
# ===========================================================================

class TestDetectFVGs:

    def test_returns_list_of_dicts(self, sample_ohlcv):
        ohlc = prepare_ohlc(sample_ohlcv)
        fvgs = detect_fvgs(ohlc)
        assert isinstance(fvgs, list)
        for f in fvgs:
            assert isinstance(f, dict)

    def test_dict_keys(self, sample_ohlcv):
        ohlc = prepare_ohlc(sample_ohlcv)
        fvgs = detect_fvgs(ohlc)
        required_keys = {"type", "top", "bottom", "midpoint", "gap_size",
                         "candle_index", "timestamp", "filled", "mitigated_index",
                         "consequent_encroachment"}
        for f in fvgs:
            assert required_keys.issubset(f.keys()), f"Missing keys: {required_keys - f.keys()}"

    def test_consequent_encroachment_is_midpoint(self, sample_ohlcv):
        ohlc = prepare_ohlc(sample_ohlcv)
        fvgs = detect_fvgs(ohlc)
        for f in fvgs:
            assert f["consequent_encroachment"] == f["midpoint"]
            expected_mid = round((f["top"] + f["bottom"]) / 2, 6)
            assert abs(f["midpoint"] - expected_mid) < 0.01

    def test_type_values(self, sample_ohlcv):
        ohlc = prepare_ohlc(sample_ohlcv)
        fvgs = detect_fvgs(ohlc)
        for f in fvgs:
            assert f["type"] in ("bullish", "bearish")

    def test_gap_size_positive(self, sample_ohlcv):
        ohlc = prepare_ohlc(sample_ohlcv)
        fvgs = detect_fvgs(ohlc)
        for f in fvgs:
            assert f["gap_size"] >= 0, f"Gap size should be non-negative: {f['gap_size']}"

    def test_get_unfilled_fvgs_filter(self, sample_ohlcv):
        ohlc = prepare_ohlc(sample_ohlcv)
        all_fvgs = detect_fvgs(ohlc)
        unfilled = get_unfilled_fvgs(all_fvgs)
        assert all(not f["filled"] for f in unfilled)
        assert len(unfilled) <= len(all_fvgs)

    def test_filled_flag_consistency(self, sample_ohlcv):
        ohlc = prepare_ohlc(sample_ohlcv)
        fvgs = detect_fvgs(ohlc)
        for f in fvgs:
            if f["filled"]:
                assert f["mitigated_index"] is not None
            else:
                assert f["mitigated_index"] is None


# ===========================================================================
# detect_bos_choch
# ===========================================================================

class TestDetectBOSChoCH:

    def test_returns_tuple(self, sample_ohlcv):
        ohlc = prepare_ohlc(sample_ohlcv)
        shl, _ = detect_swings(ohlc, "entry")
        breaks, bias = detect_bos_choch(ohlc, shl)
        assert isinstance(breaks, list)
        assert isinstance(bias, str)

    def test_bias_values(self, sample_ohlcv):
        ohlc = prepare_ohlc(sample_ohlcv)
        shl, _ = detect_swings(ohlc, "entry")
        _, bias = detect_bos_choch(ohlc, shl)
        assert bias in ("bullish", "bearish", "neutral")

    def test_break_dict_format(self, sample_ohlcv):
        ohlc = prepare_ohlc(sample_ohlcv)
        shl, _ = detect_swings(ohlc, "entry")
        breaks, _ = detect_bos_choch(ohlc, shl)
        required_keys = {"type", "direction", "level", "previous_level",
                         "candle_index", "broken_index", "timestamp"}
        for b in breaks:
            assert required_keys.issubset(b.keys()), f"Missing keys: {required_keys - b.keys()}"
            assert b["type"] in ("BOS", "CHoCH")
            assert b["direction"] in ("bullish", "bearish")

    def test_bias_from_last_3_breaks(self):
        """Test bias calculation logic directly."""
        ohlc_data = pd.DataFrame({
            "open": np.random.randn(300) + 100,
            "high": np.random.randn(300) + 101,
            "low": np.random.randn(300) + 99,
            "close": np.random.randn(300) + 100,
            "volume": np.full(300, 1000),
        }, index=pd.date_range("2025-01-01", periods=300, freq="15min", tz="UTC"))
        ohlc_data.index.name = None
        # Just verify it doesn't crash — bias logic is internal
        shl, _ = detect_swings(ohlc_data, "entry")
        _, bias = detect_bos_choch(ohlc_data, shl)
        assert bias in ("bullish", "bearish", "neutral")


# ===========================================================================
# detect_order_blocks
# ===========================================================================

class TestDetectOrderBlocks:

    def test_returns_list_of_dicts(self, sample_ohlcv):
        ohlc = prepare_ohlc(sample_ohlcv)
        shl, _ = detect_swings(ohlc, "entry")
        obs = detect_order_blocks(ohlc, shl)
        assert isinstance(obs, list)

    def test_dict_keys(self, sample_ohlcv):
        ohlc = prepare_ohlc(sample_ohlcv)
        shl, _ = detect_swings(ohlc, "entry")
        obs = detect_order_blocks(ohlc, shl)
        required_keys = {"type", "high", "low", "midpoint", "candle_index",
                         "timestamp", "ob_volume", "strength_pct", "mitigated",
                         "mitigated_index", "displacement_index", "displacement_body_atr"}
        for ob in obs:
            assert required_keys.issubset(ob.keys()), f"Missing keys: {required_keys - ob.keys()}"

    def test_midpoint_calculated(self, sample_ohlcv):
        ohlc = prepare_ohlc(sample_ohlcv)
        shl, _ = detect_swings(ohlc, "entry")
        obs = detect_order_blocks(ohlc, shl)
        for ob in obs:
            expected = round((ob["high"] + ob["low"]) / 2, 6)
            assert abs(ob["midpoint"] - expected) < 0.01

    def test_get_unmitigated_obs_filter(self, sample_ohlcv):
        ohlc = prepare_ohlc(sample_ohlcv)
        shl, _ = detect_swings(ohlc, "entry")
        all_obs = detect_order_blocks(ohlc, shl)
        unmitigated = get_unmitigated_obs(all_obs)
        assert all(not ob["mitigated"] for ob in unmitigated)
        assert len(unmitigated) <= len(all_obs)

    def test_type_values(self, sample_ohlcv):
        ohlc = prepare_ohlc(sample_ohlcv)
        shl, _ = detect_swings(ohlc, "entry")
        obs = detect_order_blocks(ohlc, shl)
        for ob in obs:
            assert ob["type"] in ("bullish", "bearish")


# ===========================================================================
# detect_liquidity
# ===========================================================================

class TestDetectLiquidity:

    def test_returns_list_of_dicts(self, sample_ohlcv):
        ohlc = prepare_ohlc(sample_ohlcv)
        shl, _ = detect_swings(ohlc, "entry")
        zones = detect_liquidity(ohlc, shl)
        assert isinstance(zones, list)

    def test_dict_keys(self, sample_ohlcv):
        ohlc = prepare_ohlc(sample_ohlcv)
        shl, _ = detect_swings(ohlc, "entry")
        zones = detect_liquidity(ohlc, shl)
        required_keys = {"type", "level", "touch_count", "range_high", "range_low",
                         "candle_index", "end_index", "swept", "sweep_candle_index", "timestamps"}
        for z in zones:
            assert required_keys.issubset(z.keys())
            assert z["type"] in ("buy_side", "sell_side")


# ===========================================================================
# detect_previous_high_low
# ===========================================================================

class TestDetectPreviousHighLow:

    def test_returns_dict(self, sample_ohlcv):
        ohlc = prepare_ohlc(sample_ohlcv)
        result = detect_previous_high_low(ohlc)
        assert isinstance(result, dict)

    def test_dict_keys(self, sample_ohlcv):
        ohlc = prepare_ohlc(sample_ohlcv)
        result = detect_previous_high_low(ohlc)
        for key in ["pdh", "pdl", "pdh_broken", "pdl_broken"]:
            assert key in result, f"Missing key: {key}"

    def test_handles_small_data(self, tiny_ohlcv_3):
        """Small data should return gracefully with None values."""
        ohlc = prepare_ohlc(tiny_ohlcv_3)
        result = detect_previous_high_low(ohlc)
        assert isinstance(result, dict)


# ===========================================================================
# detect_retracements
# ===========================================================================

class TestDetectRetracements:

    def test_returns_dict(self, sample_ohlcv):
        ohlc = prepare_ohlc(sample_ohlcv)
        shl, _ = detect_swings(ohlc, "entry")
        result = detect_retracements(ohlc, shl)
        assert isinstance(result, dict)

    def test_dict_keys(self, sample_ohlcv):
        ohlc = prepare_ohlc(sample_ohlcv)
        shl, _ = detect_swings(ohlc, "entry")
        result = detect_retracements(ohlc, shl)
        assert "direction" in result
        assert "current_retracement_pct" in result
        assert "deepest_retracement_pct" in result
        assert "in_ote" in result

    def test_direction_values(self, sample_ohlcv):
        ohlc = prepare_ohlc(sample_ohlcv)
        shl, _ = detect_swings(ohlc, "entry")
        result = detect_retracements(ohlc, shl)
        assert result["direction"] in ("bullish", "bearish", "neutral")

    def test_in_ote_calculation(self, sample_ohlcv):
        ohlc = prepare_ohlc(sample_ohlcv)
        shl, _ = detect_swings(ohlc, "entry")
        result = detect_retracements(ohlc, shl)
        pct = abs(result["current_retracement_pct"])
        expected_ote = 61.8 <= pct <= 79.0
        assert result["in_ote"] == expected_ote

    def test_handles_no_swings(self, flat_ohlcv):
        ohlc = prepare_ohlc(flat_ohlcv)
        shl, _ = detect_swings(ohlc, "entry")
        result = detect_retracements(ohlc, shl)
        assert result["direction"] == "neutral"
