"""Historical CSV data loader for backtesting.

Loads 1-minute OHLCV data from Databento-format CSV files and resamples
to all timeframes needed by the ICT detection engine.
"""

import pandas as pd


# ES futures quarterly expiry: 3rd Friday of the contract month.
# Standard roll: ~8 trading days before expiry (volume shifts to next contract).
# These are approximate roll dates for the contracts in our dataset.
ES_ROLL_DATES = {
    "ESM5": "2025-06-12",  # Roll from ESM5 (Jun) to ESU5 (Sep)
    "ESU5": "2025-09-11",  # Roll from ESU5 (Sep) to ESZ5 (Dec)
    "ESZ5": "2025-12-11",  # Roll from ESZ5 (Dec) to ESH6 (Mar)
    "ESH6": "2026-03-12",  # Roll from ESH6 (Mar) to ESM6 (Jun)
    "ESM6": "2026-06-11",  # Roll from ESM6 (Jun) to ESU6 (Sep)
    "ESU6": "2026-09-10",  # Roll from ESU6 (Sep) to ESZ6 (Dec)
    "ESZ6": "2026-12-10",  # Roll from ESZ6 (Dec) to ESH7 (Mar)
}

# Contract order for front-month stitching
ES_CONTRACT_ORDER = ["ESM5", "ESU5", "ESZ5", "ESH6", "ESM6", "ESU6", "ESZ6", "ESH7"]


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
        df = df[df["timestamp"] <= pd.Timestamp(end, tz="UTC")]

    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def load_continuous_contract(
    filepath: str,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Load CSV and stitch front-month contracts into a continuous series.

    Supports two CSV formats:
    - Databento: has ts_event, symbol columns (multi-contract, needs stitching)
    - IBKR/simple: has timestamp, open, high, low, close, volume (single series)

    Returns:
        Single continuous DataFrame with columns: timestamp, open, high, low, close, volume
    """
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
            df = df[df["timestamp"] <= pd.Timestamp(end, tz="UTC")]
        return df.sort_values("timestamp").reset_index(drop=True)

    # Databento format — load and stitch
    df = load_csv(filepath, start=start, end=end)

    if df.empty:
        return df

    # Get unique non-spread symbols sorted by contract order
    symbols = [s for s in ES_CONTRACT_ORDER if s in df["symbol"].unique()]

    if len(symbols) <= 1:
        # Only one contract — no stitching needed
        return df.drop(columns=["symbol"]).reset_index(drop=True)

    # Use roll dates to assign front-month
    result_frames = []
    for i, sym in enumerate(symbols):
        sym_df = df[df["symbol"] == sym].copy()
        if sym_df.empty:
            continue

        roll_date = ES_ROLL_DATES.get(sym)
        if roll_date and i < len(symbols) - 1:
            # Keep data up to the roll date
            sym_df = sym_df[sym_df["timestamp"] < pd.Timestamp(roll_date, tz="UTC")]
        elif i > 0:
            # For non-first contracts, start from previous contract's roll date
            prev_sym = symbols[i - 1]
            prev_roll = ES_ROLL_DATES.get(prev_sym)
            if prev_roll:
                sym_df = sym_df[sym_df["timestamp"] >= pd.Timestamp(prev_roll, tz="UTC")]

        result_frames.append(sym_df)

    if not result_frames:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    continuous = pd.concat(result_frames, ignore_index=True)
    continuous = continuous.drop(columns=["symbol"]).sort_values("timestamp").reset_index(drop=True)

    # Drop duplicate timestamps (overlap at roll boundaries)
    continuous = continuous.drop_duplicates(subset=["timestamp"], keep="last").reset_index(drop=True)

    return continuous


def resample_ohlcv(df: pd.DataFrame, target: str) -> pd.DataFrame:
    """Resample 1-minute OHLCV data to a higher timeframe.

    Timestamps are labeled by bar CLOSE time to prevent look-ahead bias.
    A bar labeled 10:15 means the bar covers 10:00-10:14 and is only
    complete at 10:15. This ensures get_windowed_data() with
    `timestamp <= current_time` never includes partially-formed bars.

    Args:
        df: DataFrame with timestamp, open, high, low, close, volume
        target: Target timeframe string (e.g. "5min", "15min", "1h", "4h", "1D")

    Returns:
        Resampled DataFrame with same column structure
    """
    if df.empty:
        return df.copy()

    temp = df.set_index("timestamp")
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
        "bias": resample_ohlcv(df_1m, "1D"),
        "swing": resample_ohlcv(df_1m, "4h"),
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
        # Only include bars whose close time <= current_time (fully completed)
        mask = df["timestamp"] <= current_time
        sliced = df[mask]
        n = lookback.get(label, 200)
        windowed[label] = sliced.tail(n).reset_index(drop=True)

    return windowed
