"""Historical CSV data loader for backtesting.

Loads 1-minute OHLCV data from Databento-format CSV files and resamples
to all timeframes needed by the ICT detection engine.
"""

from zoneinfo import ZoneInfo

import pandas as pd

_SESSION_TZ = ZoneInfo("America/New_York")

# The CME equity-index trading day runs 18:00 ET to 17:00 ET the next day.
# Daily and 4H bins are anchored here so they cover one session, not a UTC
# calendar day that straddles two.
CME_SESSION_OPEN_HOUR_ET = 18


def session_day(timestamps: pd.Series) -> pd.Series:
    """Map bar timestamps to the CME trading day they belong to.

    The trading day opens 18:00 ET and runs to 17:00 ET the next day, so the
    Sunday evening session belongs to Monday.

    Bars are pushed forward by the hours left in the day after the 18:00 ET
    open, so the evening session lands on the following date and the afternoon
    stays put.

    The shift is applied to naive ET wall-clock, not to a tz-aware timestamp.
    Doing this arithmetic on a tz-aware value uses absolute time, which drags
    Sunday-evening bars onto Saturday at every spring-forward and invents a
    Saturday session that does not exist.
    """
    local = timestamps.dt.tz_convert(_SESSION_TZ).dt.tz_localize(None)
    return (local + pd.Timedelta(hours=24 - CME_SESSION_OPEN_HOUR_ET)).dt.normalize()


def load_csv(
    filepath: str,
    symbol_filter: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Load a Databento OHLCV CSV and normalize columns.

    Args:
        filepath: Path to CSV file
        symbol_filter: If set, keep only this symbol (e.g. "ESM5")
        start: ISO date string to filter from (inclusive)
        end: ISO date string to filter to (inclusive)

    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume
    """
    df = pd.read_csv(filepath)

    # Drop spread symbols (contain "-")
    df = df[~df["symbol"].str.contains("-", na=False)].copy()

    # Filter to specific symbol if requested
    if symbol_filter:
        df = df[df["symbol"] == symbol_filter].copy()

    # Parse timestamps and normalize columns
    df["timestamp"] = pd.to_datetime(df["ts_event"], utc=True)
    df = df[["timestamp", "open", "high", "low", "close", "volume", "symbol"]].copy()

    # Ensure numeric types
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)
    df["volume"] = df["volume"].astype(int)

    # Date range filter
    if start:
        df = df[df["timestamp"] >= pd.Timestamp(start, tz="UTC")]
    if end:
        df = df[df["timestamp"] <= _end_timestamp(end)]

    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def _end_timestamp(end: str) -> pd.Timestamp:
    """Turn an end filter into an inclusive upper bound.

    A bare date such as "2026-04-06" means the whole of that day. Comparing
    against midnight would drop the final day of data.
    """
    ts = pd.Timestamp(end, tz="UTC")
    if ts == ts.normalize():
        return ts + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
    return ts


def load_continuous_contract(
    filepath: str,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Load a data file and stitch front-month contracts into a continuous series.

    Supports:
    - Databento DBN (.dbn / .dbn.zst) — read through the databento package
    - Databento CSV: has ts_event, symbol columns (multi-contract, needs stitching)
    - IBKR/simple CSV: has timestamp, open, high, low, close, volume (single series)

    Returns:
        Single continuous DataFrame with columns: timestamp, open, high, low, close, volume
    """
    if ".dbn" in filepath:
        df = _read_dbn(filepath)
        if start:
            df = df[df["timestamp"] >= pd.Timestamp(start, tz="UTC")]
        if end:
            df = df[df["timestamp"] <= _end_timestamp(end)]
        df = df.sort_values("timestamp").reset_index(drop=True)
        if "symbol" not in df.columns:
            return df
        return _stitch(df)

    # Detect format by peeking at columns
    header = pd.read_csv(filepath, nrows=0).columns.tolist()

    if "symbol" not in header and "ts_event" not in header:
        # IBKR / simple format — already a single continuous series
        df = pd.read_csv(filepath)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        for col in ("open", "high", "low", "close"):
            df[col] = df[col].astype(float)
        df["volume"] = df["volume"].astype(int)
        if start:
            df = df[df["timestamp"] >= pd.Timestamp(start, tz="UTC")]
        if end:
            df = df[df["timestamp"] <= _end_timestamp(end)]
        return df.sort_values("timestamp").reset_index(drop=True)

    # Databento format — load and stitch
    return _stitch(load_csv(filepath, start=start, end=end))


def _read_dbn(filepath: str) -> pd.DataFrame:
    """Read a Databento DBN file into our column layout.

    Kept separate from _normalize_dbn so the reshaping half stays testable
    without the databento package or a real DBN file present.
    """
    try:
        import databento as db
    except ImportError as exc:
        raise ImportError(
            "Reading .dbn files needs the databento package: pip install databento"
        ) from exc
    return _normalize_dbn(db.read_dbn(filepath).to_df())


def _normalize_dbn(df: pd.DataFrame) -> pd.DataFrame:
    """Reshape a databento to_df() frame to timestamp/OHLCV[/symbol].

    to_df() indexes on ts_event for the OHLCV schemas and returns tz-aware UTC
    timestamps and float prices, so this is a rename and a column select.
    Databento stamps ts_event at the START of the interval, which is what
    resample_ohlcv expects — it does the bar-close shift itself.
    """
    out = df.reset_index()
    if "ts_event" in out.columns:
        out = out.rename(columns={"ts_event": "timestamp"})
    elif "timestamp" not in out.columns:
        out = out.rename(columns={out.columns[0]: "timestamp"})

    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    for col in ("open", "high", "low", "close"):
        out[col] = out[col].astype(float)
    out["volume"] = out["volume"].astype(int)

    cols = ["timestamp", "open", "high", "low", "close", "volume"]
    if "symbol" in out.columns:
        # Drop calendar spreads, same as the CSV path
        out = out[~out["symbol"].str.contains("-", na=False)]
        cols.append("symbol")

    # A parent-symbol request (ES.FUT) returns spreads alongside outrights, and
    # CME's user-defined spreads do not always join their legs with a "-" — they
    # can arrive as "UD:T$: ST 0304976550". Spread prices are the difference
    # between legs and go negative, so a non-positive price is a spread that got
    # past the name check. An outright ES bar can never be at or below zero.
    priced = (out[["open", "high", "low", "close"]] > 0).all(axis=1)
    return out.loc[priced, cols].reset_index(drop=True)


def front_month_schedule(df: pd.DataFrame) -> pd.Series:
    """Work out which contract is front month on each trading day.

    Ranks contracts by their last observed bar, which is their expiry. Reading
    the order off the data avoids parsing symbols: ES uses one-digit year codes
    (ESM5), so over a multi-year file they are ambiguous by decade, and CME has
    started issuing two-digit ones (NGN25) as well.

    The front month is whichever contract traded the most volume that day,
    latched so a thin day near the roll cannot switch back to a contract that
    has already been left behind.

    Returns:
        Series indexed by session day, holding the front-month symbol.
    """
    order = (
        df.groupby("symbol")["timestamp"].max().sort_values().index.tolist()
    )
    rank = {sym: i for i, sym in enumerate(order)}

    volume = df.groupby([df["session_day"], "symbol"])["volume"].sum()
    busiest = volume.groupby(level=0).idxmax().map(lambda key: key[1])

    schedule = {}
    current = -1
    for day, sym in busiest.sort_index().items():
        current = max(current, rank[sym])
        schedule[day] = order[current]
    return pd.Series(schedule, name="front_month")


def _stitch(df: pd.DataFrame) -> pd.DataFrame:
    """Splice per-contract bars into one continuous front-month series."""
    if df.empty or "symbol" not in df.columns:
        return df.drop(columns=["symbol"], errors="ignore").reset_index(drop=True)

    if df["symbol"].nunique() <= 1:
        return df.drop(columns=["symbol"]).reset_index(drop=True)

    df = df.assign(session_day=session_day(df["timestamp"]))
    schedule = front_month_schedule(df)
    keep = df["symbol"] == df["session_day"].map(schedule)
    front = df[keep].drop(columns=["session_day"])

    # Split back into per-contract runs so roll steps can be back-adjusted out.
    runs = [g for _, g in front.groupby(
        (front["symbol"] != front["symbol"].shift()).cumsum(), sort=False
    )]
    if not runs:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    _back_adjust(runs)

    continuous = pd.concat(runs, ignore_index=True)
    continuous = continuous.drop(columns=["symbol"]).sort_values(
        "timestamp", kind="mergesort"
    ).reset_index(drop=True)
    return continuous.drop_duplicates(subset=["timestamp"], keep="last").reset_index(drop=True)


def _back_adjust(frames: list[pd.DataFrame]):
    """Shift older contracts so roll gaps stop looking like real price moves.

    Panama method: the newest contract keeps its true prices; every earlier one is
    moved by the running sum of the price steps at the roll boundaries. On ES
    those steps run 50-60 points against a median 15m bar range under 6, so
    without this every roll reads as displacement and a large FVG.

    Replaces entries of `frames` in place with adjusted copies.
    """
    steps = [
        float(frames[k + 1]["open"].iloc[0]) - float(frames[k]["close"].iloc[-1])
        for k in range(len(frames) - 1)
    ]

    adjustment = 0.0
    for k in range(len(frames) - 2, -1, -1):
        adjustment += steps[k]
        shifted = {c: frames[k][c] + adjustment for c in ("open", "high", "low", "close")}
        frames[k] = frames[k].assign(**shifted)


def resample_ohlcv(df: pd.DataFrame, target: str, session_aligned: bool = False) -> pd.DataFrame:
    """Resample 1-minute OHLCV data to a higher timeframe.

    Timestamps are labeled by bar CLOSE time to prevent look-ahead bias.
    A bar labeled 10:15 means the bar covers 10:00-10:14 and is only
    complete at 10:15. This ensures get_windowed_data() with
    `timestamp <= current_time` never includes partially-formed bars.

    Args:
        df: DataFrame with timestamp, open, high, low, close, volume
        target: Target timeframe string (e.g. "5min", "15min", "1h", "4h", "1D")
        session_aligned: Anchor bins to the CME session open (18:00 ET) instead
            of UTC midnight. Use for daily and 4H bars, where a UTC-anchored bin
            straddles two trading sessions. Sub-hourly and hourly bins fall on
            the same edges either way, so they do not need it.

    Returns:
        Resampled DataFrame with same column structure
    """
    if df.empty:
        return df.copy()

    temp = df.set_index("timestamp")
    session_shift = pd.Timedelta(hours=CME_SESSION_OPEN_HOUR_ET)

    if session_aligned:
        # Move to naive ET wall-clock and subtract the session open, so the
        # 18:00 ET open lands on midnight and plain calendar binning gives one
        # bin per trading session. Doing it on wall-clock rather than in UTC is
        # what keeps the boundary fixed across DST. pandas ignores `offset=` for
        # day frequencies, so this shift is the only way to anchor "1D".
        temp = temp.tz_convert(_SESSION_TZ).tz_localize(None)
        temp.index = temp.index - session_shift

    resampled = temp.resample(target, closed="left", label="left").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna(subset=["open"])

    # Shift timestamps from bar-open to bar-close so that filtering by
    # `timestamp <= current_time` only includes fully completed bars.
    freq = pd.tseries.frequencies.to_offset(target)
    resampled.index = resampled.index + freq

    if session_aligned:
        resampled.index = (resampled.index + session_shift).tz_localize(
            _SESSION_TZ, ambiguous=True, nonexistent="shift_forward"
        ).tz_convert("UTC")

    resampled = resampled.reset_index()
    resampled = resampled.rename(columns={"index": "timestamp"}) if "index" in resampled.columns else resampled
    return resampled


def build_multi_timeframe(
    df_1m: pd.DataFrame,
    entry_tf: str = "15min",
) -> dict[str, pd.DataFrame]:
    """Build all timeframes from 1-minute data.

    Returns a {label: DataFrame} dict with the standard multi-timeframe format,
    matching the config.TIMEFRAMES structure:
        bias  = daily
        swing = 4h
        setup = 1h
        entry = configurable (default 15m)

    Args:
        df_1m: 1-minute OHLCV DataFrame
        entry_tf: Entry timeframe string (e.g. "1min", "5min", "15min")

    Returns:
        Dict of {label: DataFrame}
    """
    return {
        "bias": resample_ohlcv(df_1m, "1D", session_aligned=True),
        "swing": resample_ohlcv(df_1m, "4h", session_aligned=True),
        "setup": resample_ohlcv(df_1m, "1h"),
        "entry": resample_ohlcv(df_1m, entry_tf),
    }


def get_windowed_data(
    all_timeframes: dict[str, pd.DataFrame],
    current_time: pd.Timestamp,
    lookback: dict[str, int] | None = None,
) -> dict[str, pd.DataFrame]:
    """Get a point-in-time window of data for each timeframe.

    Since bar timestamps represent bar CLOSE time (set by resample_ohlcv),
    filtering with `timestamp <= current_time` only includes bars that
    have fully completed by `current_time`. This prevents look-ahead bias.

    Args:
        all_timeframes: Full resampled data from build_multi_timeframe()
        current_time: The "current" bar timestamp (bar-close time)
        lookback: Max bars to include per label. Defaults to reasonable values.

    Returns:
        Windowed {label: DataFrame} — same format, but truncated to current_time
    """
    if lookback is None:
        # Estimate entry lookback from bar count if possible
        entry_df = all_timeframes.get("entry")
        entry_count = len(entry_df) if entry_df is not None else 0
        # Heuristic: if entry has many bars (1m/5m data), use larger lookback
        if entry_count > 10000:
            entry_lookback = 1000  # ~1 day of 1m bars
        elif entry_count > 5000:
            entry_lookback = 500   # ~1.7 days of 5m bars
        else:
            entry_lookback = 200   # ~3 days of 15m bars

        lookback = {
            "bias": 130,    # ~6 months of daily bars
            "swing": 160,   # ~1 month of 4h bars (6 per day * 26 days)
            "setup": 500,   # ~1 month of 1h bars
            "entry": entry_lookback,
        }

    windowed = {}
    for label, df in all_timeframes.items():
        # Only include bars whose close time <= current_time (fully completed).
        # timestamp is sorted, so searchsorted finds the cut in O(log n) instead
        # of masking and copying the whole history on every bar.
        end = int(df["timestamp"].searchsorted(current_time, side="right"))
        n = lookback.get(label, 200)
        windowed[label] = df.iloc[max(0, end - n):end].reset_index(drop=True)

    return windowed
