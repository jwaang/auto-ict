"""Tests for the historical data loader and resampling logic."""

import numpy as np
import pandas as pd
import pytest

from data.historical import resample_ohlcv, build_multi_timeframe, get_windowed_data


class TestResampleOHLCV:
    """Verify resampling produces correct bar-close timestamps and OHLCV aggregation."""

    def test_bar_close_labeling_15m(self, sample_ohlcv):
        """15m bars should be labeled by their close time, not open time."""
        resampled = resample_ohlcv(sample_ohlcv, "15min")
        # Input starts at 00:00, so first 15m bar covers 00:00-00:14
        # and should be timestamped at 00:15 (bar close)
        first_ts = resampled["timestamp"].iloc[0]
        assert first_ts.minute == 15 or first_ts.hour > 0, (
            f"First 15m bar at {first_ts} — expected bar-close labeling (00:15)"
        )

    def test_bar_close_labeling_1h(self, sample_ohlcv):
        """1h bars should be labeled by their close time."""
        resampled = resample_ohlcv(sample_ohlcv, "1h")
        first_ts = resampled["timestamp"].iloc[0]
        assert first_ts.hour >= 1 or first_ts.day > sample_ohlcv["timestamp"].iloc[0].day, (
            f"First 1h bar at {first_ts} — expected bar-close labeling"
        )

    def test_ohlcv_aggregation_correct(self, sample_ohlcv):
        """OHLCV aggregation: first open, max high, min low, last close, sum volume."""
        resampled = resample_ohlcv(sample_ohlcv, "1h")

        # Check first 1h bar against first 4 input bars (15m * 4 = 1h)
        first_hour = sample_ohlcv.head(4)
        r = resampled.iloc[0]

        assert r["open"] == first_hour["open"].iloc[0], "Open should be first bar's open"
        assert r["high"] == first_hour["high"].max(), "High should be max of period"
        assert r["low"] == first_hour["low"].min(), "Low should be min of period"
        assert r["close"] == first_hour["close"].iloc[-1], "Close should be last bar's close"
        assert r["volume"] == first_hour["volume"].sum(), "Volume should be sum"

    def test_empty_dataframe(self):
        """Resampling an empty DataFrame should return empty."""
        empty = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        result = resample_ohlcv(empty, "1h")
        assert result.empty

    def test_no_nan_rows(self, sample_ohlcv):
        """Resampled data should not contain NaN open values."""
        resampled = resample_ohlcv(sample_ohlcv, "1h")
        assert resampled["open"].notna().all()


class TestBuildMultiTimeframe:
    """Verify multi-timeframe construction."""

    def test_returns_all_labels(self, sample_ohlcv):
        mtf = build_multi_timeframe(sample_ohlcv)
        assert set(mtf.keys()) == {"bias", "swing", "setup", "entry"}

    def test_entry_has_most_bars(self, sample_ohlcv):
        """Entry (15m) should have the most bars, bias (daily) the fewest."""
        mtf = build_multi_timeframe(sample_ohlcv)
        assert len(mtf["entry"]) >= len(mtf["setup"])
        assert len(mtf["setup"]) >= len(mtf["swing"])

    def test_all_timeframes_have_required_columns(self, sample_ohlcv):
        mtf = build_multi_timeframe(sample_ohlcv)
        required = {"timestamp", "open", "high", "low", "close", "volume"}
        for label, df in mtf.items():
            assert required.issubset(set(df.columns)), (
                f"{label} missing columns: {required - set(df.columns)}"
            )


class TestGetWindowedData:
    """Verify windowed data prevents look-ahead bias."""

    def test_no_future_bars(self, sample_ohlcv):
        """Windowed data must not include any bar with timestamp > current_time."""
        all_tf = build_multi_timeframe(sample_ohlcv)
        entry = all_tf["entry"]

        if len(entry) < 20:
            pytest.skip("Not enough bars")

        mid_idx = len(entry) // 2
        current_time = entry.iloc[mid_idx]["timestamp"]
        windowed = get_windowed_data(all_tf, current_time)

        for label, df in windowed.items():
            if df.empty:
                continue
            max_ts = df["timestamp"].max()
            assert max_ts <= current_time, (
                f"{label}: contains bar at {max_ts} after current_time {current_time}"
            )

    def test_window_grows_with_time(self, sample_ohlcv):
        """Later current_time should include more or equal bars."""
        all_tf = build_multi_timeframe(sample_ohlcv)
        entry = all_tf["entry"]

        if len(entry) < 30:
            pytest.skip("Not enough bars")

        t1 = entry.iloc[10]["timestamp"]
        t2 = entry.iloc[20]["timestamp"]
        w1 = get_windowed_data(all_tf, t1)
        w2 = get_windowed_data(all_tf, t2)

        for label in all_tf:
            assert len(w2[label]) >= len(w1[label]), (
                f"{label}: later window has fewer bars ({len(w2[label])}) "
                f"than earlier ({len(w1[label])})"
            )

    def test_lookback_limits(self, sample_ohlcv):
        """Windowed data should respect lookback limits."""
        all_tf = build_multi_timeframe(sample_ohlcv)
        entry = all_tf["entry"]

        if len(entry) < 10:
            pytest.skip("Not enough bars")

        last_time = entry.iloc[-1]["timestamp"]
        lookback = {"bias": 5, "swing": 10, "setup": 20, "entry": 30}
        windowed = get_windowed_data(all_tf, last_time, lookback=lookback)

        for label, limit in lookback.items():
            assert len(windowed[label]) <= limit, (
                f"{label}: {len(windowed[label])} bars exceeds lookback {limit}"
            )
