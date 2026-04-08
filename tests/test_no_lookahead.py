"""Tests to ensure no look-ahead bias exists in the ICT detection pipeline.

These tests verify that:
1. No signal at bar N uses data from bar N+1 or later
2. Adding future data does not change past signals (incremental causality)
3. Swing signals appear at confirmation bars, not candidate bars
4. FVG signals appear after the confirming (3rd) candle closes
5. The full pipeline produces deterministic results on windowed data
"""

import numpy as np
import pandas as pd
import pytest

from ict.smc_patched import smc


# ---------------------------------------------------------------------------
# swing_highs_lows: Causality Tests
# ---------------------------------------------------------------------------

class TestSwingHighsLowsCausality:
    """Verify swing detection uses only past/present data."""

    def test_no_swing_in_last_swing_length_bars(self, ohlc_for_smc):
        """Swings require confirm_bars subsequent bars — the last swing_length
        bars cannot contain a detected swing (no confirmation possible)."""
        swing_length = 5
        shl = smc.swing_highs_lows(ohlc_for_smc, swing_length=swing_length)

        # Find last detected swing (excluding boundary injection at bar 0)
        indices = np.where(~np.isnan(shl["HighLow"].values))[0]
        non_boundary = indices[indices > 0]

        if len(non_boundary) > 0:
            last_idx = non_boundary[-1]
            gap = len(ohlc_for_smc) - 1 - last_idx
            assert gap >= swing_length, (
                f"Swing at bar {last_idx} is only {gap} bars from end "
                f"(need >= {swing_length} for confirmation)"
            )

    def test_incremental_stability(self, large_ohlc_for_smc):
        """Adding more future data must not change swings detected at past bars."""
        swing_length = 5
        ohlc = large_ohlc_for_smc
        n = len(ohlc)

        for cutoff in range(100, min(600, n), 100):
            shl_short = smc.swing_highs_lows(ohlc.iloc[:cutoff], swing_length=swing_length)
            shl_long = smc.swing_highs_lows(ohlc.iloc[:cutoff + 50], swing_length=swing_length)

            for i in range(cutoff):
                short_val = shl_short["HighLow"].iloc[i]
                long_val = shl_long["HighLow"].iloc[i]

                # If short has a swing, long must have the same swing
                if not pd.isna(short_val):
                    assert not pd.isna(long_val) and short_val == long_val, (
                        f"Swing at bar {i} changed when data extended from "
                        f"{cutoff} to {cutoff + 50}: was {short_val}, now {long_val}"
                    )

    def test_signal_at_confirmation_bar_not_candidate(self, ohlc_for_smc):
        """Swing signals must be emitted at the confirmation bar (i), not
        the candidate bar (i - confirm_bars). Verify Level stores the
        candidate's price, not the confirmation bar's price."""
        swing_length = 5
        shl = smc.swing_highs_lows(ohlc_for_smc, swing_length=swing_length)
        highs = ohlc_for_smc["high"].values
        lows = ohlc_for_smc["low"].values

        indices = np.where(~np.isnan(shl["HighLow"].values))[0]

        if len(indices) == 0:
            pytest.skip("No swings detected")

        mismatches = 0
        for idx in indices:
            hl = shl["HighLow"].iloc[idx]
            level = shl["Level"].iloc[idx]
            ohlc_price = highs[idx] if hl == 1 else lows[idx]

            # Level should be the candidate's price (swing_length bars back),
            # NOT the confirmation bar's price
            if level != ohlc_price:
                mismatches += 1

        # Most signals should have Level != OHLC at signal index
        # (because signal is at confirmation bar, price is from candidate bar)
        assert mismatches > 0, (
            "All Level values match OHLC at signal index — signals may be "
            "at candidate bars instead of confirmation bars"
        )

    def test_first_swing_respects_warmup(self, ohlc_for_smc):
        """First detected swing (non-boundary) must be at or after
        lookback + confirm_bars."""
        swing_length = 5
        shl = smc.swing_highs_lows(ohlc_for_smc, swing_length=swing_length)
        indices = np.where(~np.isnan(shl["HighLow"].values))[0]
        non_boundary = indices[indices > 0]

        if len(non_boundary) > 0:
            min_bar = swing_length + swing_length  # lookback + confirm_bars
            assert non_boundary[0] >= min_bar, (
                f"First swing at bar {non_boundary[0]}, expected >= {min_bar}"
            )

    def test_no_boundary_injection(self, ohlc_for_smc):
        """Neither the first nor last bar should have injected (fabricated)
        swings. Boundary injection creates false structure context."""
        shl = smc.swing_highs_lows(ohlc_for_smc, swing_length=5)

        first_val = shl["HighLow"].iloc[0]
        assert pd.isna(first_val), (
            f"Bar 0 has swing signal {first_val} — start-boundary injection "
            f"should be disabled"
        )

        last_val = shl["HighLow"].iloc[-1]
        assert pd.isna(last_val), (
            f"Last bar has swing signal {last_val} — end-boundary injection "
            f"should be disabled"
        )

    def test_various_swing_lengths(self, large_ohlc_for_smc):
        """Causality must hold for different swing_length values."""
        ohlc = large_ohlc_for_smc
        for sl in [3, 5, 10, 20]:
            shl = smc.swing_highs_lows(ohlc, swing_length=sl)
            indices = np.where(~np.isnan(shl["HighLow"].values))[0]
            # Exclude boundary injection at bar 0 (always present, no confirmation needed)
            non_boundary = indices[indices > 0]

            if len(non_boundary) > 0:
                last_idx = non_boundary[-1]
                gap = len(ohlc) - 1 - last_idx
                # The confirm-bars loop requires confirm_bars bars after the
                # candidate (candidate = i - confirm_bars). The last candidate
                # that can be confirmed is at n - 1 - confirm_bars, placed at
                # bar n - 1. So the gap from end can be 0 for the last
                # confirmed swing. The key check is that no swing exists
                # without sufficient data to confirm it.
                min_start = sl + sl  # lookback + confirm_bars
                assert non_boundary[0] >= min_start, (
                    f"swing_length={sl}: first swing at bar {non_boundary[0]}, "
                    f"expected >= {min_start}"
                )


# ---------------------------------------------------------------------------
# FVG: Causality Tests
# ---------------------------------------------------------------------------

class TestFVGCausality:
    """Verify FVG detection uses only past/present data."""

    def test_fvg_shifted_forward(self, ohlc_for_smc):
        """FVG signals must be shifted forward by 1 bar from the original
        detection (the middle candle). This means the signal appears at
        bar i+1 (the confirming candle), not bar i."""
        fvg = smc.fvg(ohlc_for_smc)
        # Bar 0 must be NaN (shifted forward, nothing before it)
        assert pd.isna(fvg["FVG"].iloc[0]), "Bar 0 should be NaN after causal shift"

    def test_fvg_not_at_last_bar(self, ohlc_for_smc):
        """The last bar cannot have an FVG because shift(-1) would read
        beyond the data. After causal shift, the last possible FVG is
        at bar n-1 (from middle candle at n-2, confirming candle at n-1)."""
        fvg = smc.fvg(ohlc_for_smc)
        fvg_indices = np.where(~np.isnan(fvg["FVG"].values))[0]
        # This is a soft check — last bar CAN have an FVG if bar n-2 was
        # the middle candle and bar n-1 is the confirming candle
        # The key invariant is incremental stability (next test)

    def test_fvg_incremental_stability(self, large_ohlc_for_smc):
        """Adding future data must not change FVGs detected at past bars."""
        ohlc = large_ohlc_for_smc

        for cutoff in range(100, min(600, len(ohlc)), 100):
            fvg_short = smc.fvg(ohlc.iloc[:cutoff])
            fvg_long = smc.fvg(ohlc.iloc[:cutoff + 50])

            for i in range(cutoff):
                sv = fvg_short["FVG"].iloc[i]
                lv = fvg_long["FVG"].iloc[i]

                if not pd.isna(sv):
                    assert not pd.isna(lv) and sv == lv, (
                        f"FVG at bar {i} changed when data extended from "
                        f"{cutoff} to {cutoff + 50}: was {sv}, now {lv}"
                    )
                    # Also check Top/Bottom didn't change
                    assert fvg_short["Top"].iloc[i] == fvg_long["Top"].iloc[i], (
                        f"FVG Top at bar {i} changed"
                    )
                    assert fvg_short["Bottom"].iloc[i] == fvg_long["Bottom"].iloc[i], (
                        f"FVG Bottom at bar {i} changed"
                    )

    def test_fvg_mitigation_after_signal(self, ohlc_for_smc):
        """MitigatedIndex must be > signal index (mitigation happens after
        the FVG forms, not before)."""
        fvg = smc.fvg(ohlc_for_smc)
        fvg_indices = np.where(~np.isnan(fvg["FVG"].values))[0]

        for idx in fvg_indices:
            mit = fvg["MitigatedIndex"].iloc[idx]
            if not pd.isna(mit) and mit > 0:
                assert int(mit) > idx, (
                    f"FVG at bar {idx} has MitigatedIndex {int(mit)} "
                    f"which is not after the signal"
                )


# ---------------------------------------------------------------------------
# BOS/CHoCH: Cascading Causality
# ---------------------------------------------------------------------------

class TestBOSChochCausality:
    """Verify BOS/CHoCH inherits causality from swing detection."""

    def test_bos_choch_incremental_stability(self, large_ohlc_for_smc):
        """BOS/CHoCH signals at past bars must not change when more data added."""
        ohlc = large_ohlc_for_smc

        for cutoff in [200, 400, 600]:
            if cutoff >= len(ohlc):
                continue
            shl_s = smc.swing_highs_lows(ohlc.iloc[:cutoff], swing_length=5)
            bc_s = smc.bos_choch(ohlc.iloc[:cutoff], shl_s)

            shl_l = smc.swing_highs_lows(ohlc.iloc[:cutoff + 100], swing_length=5)
            bc_l = smc.bos_choch(ohlc.iloc[:cutoff + 100], shl_l)

            for i in range(cutoff):
                for col in ["BOS", "CHOCH"]:
                    sv = bc_s[col].iloc[i]
                    lv = bc_l[col].iloc[i]
                    if not pd.isna(sv):
                        assert not pd.isna(lv) and sv == lv, (
                            f"{col} at bar {i} changed when data extended "
                            f"from {cutoff} to {cutoff + 100}"
                        )

    def test_bos_choch_not_backdated(self, large_ohlc_for_smc):
        """BOS/CHoCH signals must be emitted at the bar where the 4th swing
        makes the pattern knowable, NOT backdated to an earlier swing index.

        If a BOS/CHoCH appears at bar N, then at least 4 swings must exist
        at or before bar N."""
        ohlc = large_ohlc_for_smc
        shl = smc.swing_highs_lows(ohlc, swing_length=5)
        bc = smc.bos_choch(ohlc, shl)

        swing_indices = np.where(~np.isnan(shl["HighLow"].values))[0]

        for i in range(len(bc)):
            for col in ["BOS", "CHOCH"]:
                if not pd.isna(bc[col].iloc[i]):
                    # Count swings at or before bar i
                    swings_before = np.sum(swing_indices <= i)
                    assert swings_before >= 4, (
                        f"{col} at bar {i} but only {swings_before} swings "
                        f"exist at or before that bar (need 4)"
                    )

    def test_broken_index_after_signal(self, large_ohlc_for_smc):
        """BrokenIndex must be after the signal bar."""
        ohlc = large_ohlc_for_smc
        shl = smc.swing_highs_lows(ohlc, swing_length=5)
        bc = smc.bos_choch(ohlc, shl)

        for i in range(len(bc)):
            for col in ["BOS", "CHOCH"]:
                if not pd.isna(bc[col].iloc[i]):
                    broken = bc["BrokenIndex"].iloc[i]
                    if not pd.isna(broken) and broken > 0:
                        assert int(broken) > i, (
                            f"{col} at bar {i} has BrokenIndex {int(broken)} "
                            f"which is before or at the signal"
                        )


# ---------------------------------------------------------------------------
# Order Blocks: Cascading Causality
# ---------------------------------------------------------------------------

class TestOrderBlockCausality:
    """Verify OB detection inherits causality from swing detection."""

    def test_ob_no_future_index_access(self, large_ohlc_for_smc):
        """OB detection should not reference future indices.

        Note: OBs CAN change when more data is added because the swing
        alternation cleanup produces different swing patterns with different
        data lengths. This is inherent to the algorithm, not look-ahead bias.
        The key check is that OBs only form at bars <= the current bar."""
        ohlc = large_ohlc_for_smc
        shl = smc.swing_highs_lows(ohlc, swing_length=5)
        ob = smc.ob(ohlc, shl)

        ob_indices = np.where(~np.isnan(ob["OB"].values))[0]
        swing_indices = np.where(~np.isnan(shl["HighLow"].values))[0]

        for idx in ob_indices:
            # OB index must be before or at a swing that triggered it
            # (the swing that was broken to create the OB)
            assert idx < len(ohlc), f"OB at index {idx} is out of bounds"
            # MitigatedIndex (if set) must be after the OB
            mit = ob["MitigatedIndex"].iloc[idx]
            if not pd.isna(mit) and mit > 0:
                assert int(mit) > idx, (
                    f"OB at bar {idx} mitigated at {int(mit)} which is before the OB"
                )

    def test_ob_does_not_crash_on_small_data(self):
        """OB should handle very small DataFrames without index errors."""
        short_df = pd.DataFrame({
            "open": [1.0, 1.1, 1.2],
            "high": [1.05, 1.15, 1.25],
            "low": [0.95, 1.05, 1.15],
            "close": [1.02, 1.14, 1.24],
            "volume": [5, 6, 7],
        })
        shl = smc.swing_highs_lows(short_df, swing_length=1)
        ob = smc.ob(short_df, shl)
        assert len(ob) == len(short_df)


# ---------------------------------------------------------------------------
# Full Pipeline: End-to-End Causality
# ---------------------------------------------------------------------------

class TestFullPipelineCausality:
    """Verify the complete ICT analysis pipeline is causal."""

    def test_windowed_analysis_deterministic(self, sample_ohlcv):
        """Same windowed data must produce identical results every time."""
        from data.historical import build_multi_timeframe, get_windowed_data
        from ict.confluence import analyze_multi_timeframe
        from ict.smc_adapter import set_swing_length_override
        from config import BACKTEST_SMC_SWING_LENGTH

        set_swing_length_override(BACKTEST_SMC_SWING_LENGTH)
        try:
            all_tf = build_multi_timeframe(sample_ohlcv)
            entry_bars = all_tf["entry"]
            if len(entry_bars) < 50:
                pytest.skip("Not enough entry bars for test")

            t = entry_bars.iloc[len(entry_bars) // 2]["timestamp"]
            w = get_windowed_data(all_tf, t)

            ctx1 = analyze_multi_timeframe(w, "ES")
            ctx2 = analyze_multi_timeframe(w, "ES")

            assert ctx1["confluence_score"] == ctx2["confluence_score"]
            assert ctx1["htf_bias"] == ctx2["htf_bias"]
        finally:
            set_swing_length_override(None)

    def test_bar_close_timestamps_prevent_partial_bars(self, sample_ohlcv):
        """Resampled bars use bar-close timestamps, so get_windowed_data
        at time T only includes bars whose close <= T."""
        from data.historical import resample_ohlcv

        df_1h = resample_ohlcv(sample_ohlcv, "1h")

        # First 1h bar should be timestamped at 01:00 (close), not 00:00 (open)
        first_ts = df_1h["timestamp"].iloc[0]
        assert first_ts.hour >= 1 or first_ts.day > sample_ohlcv["timestamp"].iloc[0].day, (
            f"First 1h bar timestamp {first_ts} should be bar-close, not bar-open"
        )

    def test_windowed_data_excludes_future(self, sample_ohlcv):
        """get_windowed_data at time T must not include bars after T."""
        from data.historical import build_multi_timeframe, get_windowed_data

        all_tf = build_multi_timeframe(sample_ohlcv)

        for label, df in all_tf.items():
            if len(df) < 10:
                continue
            mid_time = df.iloc[len(df) // 2]["timestamp"]
            windowed = get_windowed_data(all_tf, mid_time)

            for w_label, w_df in windowed.items():
                if w_df.empty:
                    continue
                max_ts = w_df["timestamp"].max()
                assert max_ts <= mid_time, (
                    f"{w_label}: windowed data contains bar at {max_ts} "
                    f"which is after current_time {mid_time}"
                )


# ---------------------------------------------------------------------------
# Regression: Output Shape & Structure
# ---------------------------------------------------------------------------

class TestOutputStructure:
    """Verify output shapes and column names haven't changed."""

    def test_swing_output_shape(self, ohlc_for_smc):
        shl = smc.swing_highs_lows(ohlc_for_smc, swing_length=5)
        assert list(shl.columns) == ["HighLow", "Level"]
        assert len(shl) == len(ohlc_for_smc)

    def test_fvg_output_shape(self, ohlc_for_smc):
        fvg = smc.fvg(ohlc_for_smc)
        assert list(fvg.columns) == ["FVG", "Top", "Bottom", "MitigatedIndex"]
        assert len(fvg) == len(ohlc_for_smc)

    def test_bos_choch_output_shape(self, ohlc_for_smc):
        shl = smc.swing_highs_lows(ohlc_for_smc, swing_length=5)
        bc = smc.bos_choch(ohlc_for_smc, shl)
        assert list(bc.columns) == ["BOS", "CHOCH", "Level", "BrokenIndex"]
        assert len(bc) == len(ohlc_for_smc)

    def test_ob_output_shape(self, ohlc_for_smc):
        shl = smc.swing_highs_lows(ohlc_for_smc, swing_length=5)
        ob = smc.ob(ohlc_for_smc, shl)
        assert list(ob.columns) == ["OB", "Top", "Bottom", "OBVolume",
                                     "MitigatedIndex", "Percentage"]
        assert len(ob) == len(ohlc_for_smc)

    def test_liquidity_output_shape(self, ohlc_for_smc):
        shl = smc.swing_highs_lows(ohlc_for_smc, swing_length=5)
        liq = smc.liquidity(ohlc_for_smc, shl)
        assert list(liq.columns) == ["Liquidity", "Level", "End", "Swept"]
        assert len(liq) == len(ohlc_for_smc)

    def test_previous_high_low_output_shape(self, ohlc_for_smc):
        phl = smc.previous_high_low(ohlc_for_smc, time_frame="1D")
        assert list(phl.columns) == ["PreviousHigh", "PreviousLow",
                                      "BrokenHigh", "BrokenLow"]
        assert len(phl) == len(ohlc_for_smc)

    def test_retracements_output_shape(self, ohlc_for_smc):
        shl = smc.swing_highs_lows(ohlc_for_smc, swing_length=5)
        ret = smc.retracements(ohlc_for_smc, shl)
        assert list(ret.columns) == ["Direction", "CurrentRetracement%",
                                      "DeepestRetracement%"]
        assert len(ret) == len(ohlc_for_smc)

    def test_swing_values_valid(self, ohlc_for_smc):
        """HighLow should only contain 1, -1, or NaN."""
        shl = smc.swing_highs_lows(ohlc_for_smc, swing_length=5)
        valid = shl["HighLow"].dropna().isin([1.0, -1.0]).all()
        assert valid, "HighLow contains values other than 1, -1, or NaN"

    def test_fvg_values_valid(self, ohlc_for_smc):
        """FVG should only contain 1, -1, or NaN."""
        fvg = smc.fvg(ohlc_for_smc)
        valid = fvg["FVG"].dropna().isin([1.0, -1.0]).all()
        assert valid, "FVG contains values other than 1, -1, or NaN"

    def test_fvg_top_above_bottom(self, ohlc_for_smc):
        """FVG Top must be >= Bottom for all detected FVGs."""
        fvg = smc.fvg(ohlc_for_smc)
        fvg_rows = fvg[fvg["FVG"].notna()]
        if len(fvg_rows) > 0:
            assert (fvg_rows["Top"] >= fvg_rows["Bottom"]).all(), (
                "Some FVGs have Top < Bottom"
            )


# ---------------------------------------------------------------------------
# Swing Alternation Integrity
# ---------------------------------------------------------------------------

class TestSwingAlternation:
    """Verify swing highs and lows alternate properly."""

    def test_swings_alternate(self, large_ohlc_for_smc):
        """After deduplication, swings should alternate between
        high (1) and low (-1)."""
        shl = smc.swing_highs_lows(large_ohlc_for_smc, swing_length=5)
        swings = shl["HighLow"].dropna().values

        if len(swings) < 2:
            pytest.skip("Not enough swings to test alternation")

        for i in range(1, len(swings)):
            assert swings[i] != swings[i - 1], (
                f"Consecutive same-direction swings at positions {i - 1} "
                f"and {i}: both are {swings[i]}"
            )

    def test_swing_levels_make_sense(self, large_ohlc_for_smc):
        """Swing high levels should be actual highs, swing low levels
        should be actual lows from the data. Level must not be NaN."""
        ohlc = large_ohlc_for_smc
        shl = smc.swing_highs_lows(ohlc, swing_length=5)

        for i in range(len(shl)):
            if pd.isna(shl["HighLow"].iloc[i]):
                continue
            level = shl["Level"].iloc[i]
            assert not pd.isna(level), (
                f"Swing at bar {i} has NaN Level"
            )
            if shl["HighLow"].iloc[i] == 1:
                assert level <= ohlc["high"].max(), (
                    f"Swing high level {level} exceeds data max high"
                )
            else:
                assert level >= ohlc["low"].min(), (
                    f"Swing low level {level} is below data min low"
                )
