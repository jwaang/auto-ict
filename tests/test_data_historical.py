"""Tests for the historical data loader and resampling logic."""

import numpy as np
import pandas as pd
import pytest

from data.historical import (
    resample_ohlcv,
    build_multi_timeframe,
    get_windowed_data,
    load_continuous_contract,
    front_month_schedule,
    session_day,
    _normalize_dbn,
)


ET = "America/New_York"


def _write_databento_csv(path, contracts):
    """Write a minimal Databento-format CSV covering several contract months.

    contracts: list of (symbol, start, end, price, volume_fn) where volume_fn
    takes a timestamp and returns that bar's volume. Every contract is listed
    across its whole life so the front-month windows overlap the way the real
    feed does.
    """
    rows = []
    for symbol, start, end, price, volume_fn in contracts:
        for ts in pd.date_range(start, end, freq="1h", tz="UTC"):
            rows.append({
                "ts_event": ts.isoformat(),
                "open": price, "high": price + 1,
                "low": price - 1, "close": price,
                "volume": volume_fn(ts), "symbol": symbol,
            })
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


ROLL = pd.Timestamp("2025-06-16", tz="UTC")


class TestContractStitching:
    """Front month is whichever contract trades the most that day. Only its bars
    may survive, or thin back-month bars land on timestamps the true front month
    already occupies."""

    @pytest.fixture
    def multi_contract_csv(self, tmp_path):
        # ESM5 dominates until ROLL, then ESU5 takes over. ESZ5 is always thin.
        return _write_databento_csv(tmp_path / "es.csv", [
            ("ESM5", "2025-04-07", "2025-06-20", 5000.0, lambda t: 900 if t < ROLL else 10),
            ("ESU5", "2025-04-07", "2025-09-19", 5100.0, lambda t: 100 if t < ROLL else 900),
            ("ESZ5", "2025-04-07", "2025-12-19", 5200.0, lambda t: 5),
        ])

    def test_one_bar_per_timestamp(self, multi_contract_csv):
        df = load_continuous_contract(str(multi_contract_csv))
        assert not df["timestamp"].duplicated().any()

    def test_rolls_where_volume_crosses(self, multi_contract_csv):
        """The switch must land on the volume crossover, not a fixed offset."""
        raw = pd.read_csv(multi_contract_csv)
        raw["timestamp"] = pd.to_datetime(raw["ts_event"], utc=True)
        raw["session_day"] = session_day(raw["timestamp"])
        schedule = front_month_schedule(raw)
        changes = schedule[schedule != schedule.shift()]
        # ESM5 then ESU5 on volume. ESZ5 follows only because it is the sole
        # contract still listed after ESU5 expires, which is also correct.
        assert list(changes)[:2] == ["ESM5", "ESU5"]
        assert str(changes.index[1].date()) == "2025-06-16"

    def test_no_back_month_leak(self, multi_contract_csv):
        """Only one contract may contribute bars in the pre-roll window. Each
        contract here is flat at its own level, so more than one distinct close
        means more than one contract survived."""
        df = load_continuous_contract(str(multi_contract_csv))
        early = df[df["timestamp"] < ROLL]
        assert len(early) > 0
        assert early["close"].nunique() == 1

    def test_never_rolls_backwards(self, multi_contract_csv):
        """A thin day must not hand the front month back to an earlier expiry."""
        raw = pd.read_csv(multi_contract_csv)
        raw["timestamp"] = pd.to_datetime(raw["ts_event"], utc=True)
        raw["session_day"] = session_day(raw["timestamp"])
        schedule = front_month_schedule(raw)
        order = {"ESM5": 0, "ESU5": 1, "ESZ5": 2}
        ranks = [order[s] for s in schedule]
        assert ranks == sorted(ranks)

    def test_back_adjustment_removes_roll_gaps(self, multi_contract_csv):
        """Roll boundaries must not leave a price step the FVG detector would
        read as a real gap. Every contract here is flat, so after adjustment the
        whole stitched series is flat too."""
        df = load_continuous_contract(str(multi_contract_csv))
        steps = df["close"].diff().abs().dropna()
        assert steps.max() == pytest.approx(0.0, abs=1e-6)

    def test_deterministic_across_repeat_loads(self, multi_contract_csv):
        a = load_continuous_contract(str(multi_contract_csv))
        b = load_continuous_contract(str(multi_contract_csv))
        pd.testing.assert_frame_equal(a, b)


class TestSessionDay:
    """Trading days must be derived on naive ET wall-clock. Subtracting 18h from
    a tz-aware timestamp does absolute-time arithmetic, which pushes Sunday
    evening bars into Saturday at every spring-forward and invents a Saturday
    session that does not exist."""

    def test_evening_belongs_to_next_day(self):
        ts = pd.Series(pd.to_datetime(["2025-06-15 22:30:00-04:00"], utc=True))
        assert str(session_day(ts).iloc[0].date()) == "2025-06-16"

    def test_afternoon_belongs_to_same_day(self):
        ts = pd.Series(pd.to_datetime(["2025-06-16 14:00:00-04:00"], utc=True))
        assert str(session_day(ts).iloc[0].date()) == "2025-06-16"

    def test_no_saturday_session_at_spring_forward(self):
        """2026-03-08 is the spring-forward. Sunday evening bars must map to
        Monday the 9th, never Saturday the 7th."""
        evening = pd.date_range("2026-03-08 18:00", "2026-03-08 23:59",
                                freq="1min", tz=ET)
        days = session_day(pd.Series(evening.tz_convert("UTC")))
        assert sorted({str(d.date()) for d in days}) == ["2026-03-09"]
        assert not any(d.weekday() == 5 for d in days)


class TestEndDateFilter:
    def test_bare_end_date_includes_whole_day(self, tmp_path):
        """`end="2025-04-08"` means all of the 8th, not just its midnight bar."""
        path = _write_databento_csv(tmp_path / "one.csv", [
            ("ESM5", "2025-04-07", "2025-04-09", 5000.0, lambda t: 100),
        ])
        df = load_continuous_contract(str(path), end="2025-04-08")
        last = df["timestamp"].max()
        assert last.date() == pd.Timestamp("2025-04-08").date()
        assert last.hour == 23, f"final day truncated at {last}"


class TestDBNNormalization:
    """The read half needs the databento package and a real file; this covers
    the reshaping half, which is where the format assumptions live."""

    @staticmethod
    def _to_df_like(with_symbol=True):
        """Mimic databento's DBNStore.to_df(): ts_event index, float prices."""
        idx = pd.DatetimeIndex(
            pd.date_range("2025-04-07", periods=3, freq="1min", tz="UTC"), name="ts_event"
        )
        data = {"open": [1.0, 2.0, 3.0], "high": [1.5, 2.5, 3.5],
                "low": [0.5, 1.5, 2.5], "close": [1.2, 2.2, 3.2], "volume": [10, 20, 30]}
        if with_symbol:
            data["symbol"] = ["ESM5", "ESM5", "ESM5-ESU5"]
        return pd.DataFrame(data, index=idx)

    def test_index_becomes_timestamp_column(self):
        out = _normalize_dbn(self._to_df_like(with_symbol=False))
        assert list(out.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
        assert str(out["timestamp"].dt.tz) == "UTC"

    def test_drops_calendar_spreads(self):
        out = _normalize_dbn(self._to_df_like())
        assert list(out["symbol"]) == ["ESM5", "ESM5"]

    def test_feeds_resample_unchanged(self):
        """ts_event is the interval START, which is what resample_ohlcv wants —
        it applies the bar-close shift itself."""
        out = _normalize_dbn(self._to_df_like(with_symbol=False))
        bars = resample_ohlcv(out, "1min")
        assert bars["timestamp"].iloc[0] == out["timestamp"].iloc[0] + pd.Timedelta(minutes=1)


class TestSessionAlignment:
    """Daily and 4H bars must cover one CME session (18:00 ET to 17:00 ET),
    not a UTC calendar day that straddles two."""

    @staticmethod
    def _bars(start, end):
        idx = pd.date_range(start, end, freq="1min", tz="UTC")
        return pd.DataFrame({
            "timestamp": idx,
            "open": 5000.0, "high": 5001.0, "low": 4999.0, "close": 5000.0,
            "volume": 1,
        })

    @pytest.fixture
    def within_dst(self):
        """February only — no DST change, so the grid must be exact."""
        return self._bars("2026-02-01", "2026-02-28")

    @pytest.fixture
    def across_dst(self):
        """Spans the March 2026 spring-forward."""
        return self._bars("2026-02-01", "2026-04-15")

    def test_daily_bars_close_at_session_open(self, within_dst):
        daily = resample_ohlcv(within_dst, "1D", session_aligned=True)
        hours = daily["timestamp"].dt.tz_convert(ET).dt.hour.unique()
        assert list(hours) == [18]

    def test_daily_alignment_survives_dst(self, across_dst):
        """Across the March change every daily bar must still close at 18:00 ET.
        The absolute gap is 23h on the transition day — that is the point: the
        boundary tracks the exchange's wall clock, not a fixed 24 hours."""
        daily = resample_ohlcv(across_dst, "1D", session_aligned=True)
        et = daily["timestamp"].dt.tz_convert(ET)
        assert list(et.dt.hour.unique()) == [18]
        gaps = et.diff().dropna()
        assert gaps.min() == pd.Timedelta(hours=23)
        assert gaps.max() == pd.Timedelta(hours=24)

    def test_4h_bars_anchor_to_session(self, within_dst):
        h4 = resample_ohlcv(within_dst, "4h", session_aligned=True)
        hours = sorted(h4["timestamp"].dt.tz_convert(ET).dt.hour.unique())
        assert hours == [2, 6, 10, 14, 18, 22]

    def test_4h_dst_gap_shifts_forward(self, across_dst):
        """On spring-forward the 02:00 ET label does not exist. It must shift to
        03:00 rather than raise, and only that one bar may leave the grid."""
        h4 = resample_ohlcv(across_dst, "4h", session_aligned=True)
        et_hours = h4["timestamp"].dt.tz_convert(ET).dt.hour
        off_grid = et_hours[~et_hours.isin([2, 6, 10, 14, 18, 22])]
        assert list(off_grid.unique()) == [3]
        assert len(off_grid) == 1

    def test_unaligned_default_unchanged(self, within_dst):
        """Hourly and finer bins land on the same edges either way, so the
        default path must stay exactly as it was."""
        a = resample_ohlcv(within_dst, "1h")
        b = resample_ohlcv(within_dst, "1h", session_aligned=True)
        pd.testing.assert_frame_equal(a, b)


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
