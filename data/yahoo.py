"""Yahoo Finance OHLC data fetcher using urllib (no external dependencies)."""

import json
import urllib.request
from datetime import datetime, timezone

import pandas as pd

_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def fetch_ohlc(ticker: str, interval: str = "1d", range_: str = "6mo") -> pd.DataFrame:
    """Fetch OHLC candle data from Yahoo Finance chart API.

    Args:
        ticker: Symbol (e.g. "AAPL", "BTC-USD", "ES=F")
        interval: Candle interval ("1m","5m","15m","1h","1d","1wk","1mo")
        range_: Lookback range ("1d","5d","1mo","3mo","6mo","1y","5y","max")

    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume
    """
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?interval={interval}&range={range_}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Yahoo Finance API error {e.code} for {ticker}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error fetching {ticker}: {e.reason}") from e

    result = data["chart"]["result"][0]
    timestamps = result["timestamp"]
    quotes = result["indicators"]["quote"][0]

    rows = []
    for i in range(len(timestamps)):
        o = quotes["open"][i]
        h = quotes["high"][i]
        l = quotes["low"][i]
        c = quotes["close"][i]
        v = quotes["volume"][i] if quotes.get("volume") else 0
        if o is None or c is None:
            continue
        rows.append({
            "timestamp": datetime.fromtimestamp(timestamps[i], tz=timezone.utc),
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
            "volume": int(v) if v else 0,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError(f"No data returned for {ticker} ({interval}/{range_})")
    return df


def fetch_multi_timeframe(ticker: str, timeframes: dict | None = None) -> dict[str, pd.DataFrame]:
    """Fetch OHLC data for multiple timeframes.

    Args:
        ticker: Symbol
        timeframes: Dict of {label: {interval, range}} or None for defaults

    Returns:
        Dict of {label: DataFrame}
    """
    if timeframes is None:
        from config import TIMEFRAMES
        timeframes = TIMEFRAMES

    results = {}
    for label, params in timeframes.items():
        df = fetch_ohlc(ticker, params["interval"], params["range"])

        # Aggregate if needed (e.g. 1h → 4h since Yahoo doesn't have native 4h)
        agg_to = params.get("aggregate_to")
        if agg_to:
            df = _aggregate_candles(df, agg_to)

        results[label] = df
    return results


def _aggregate_candles(df: pd.DataFrame, target_interval: str) -> pd.DataFrame:
    """Aggregate candles to a higher timeframe (e.g. 1h → 4h).

    Args:
        df: Source DataFrame with timestamp column
        target_interval: Target interval string (e.g. "4h", "2h")
    """
    df = df.copy()
    df["ts_agg"] = df["timestamp"].dt.floor(target_interval.replace("h", "h"))
    agg = df.groupby("ts_agg").agg({
        "timestamp": "first",
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).reset_index(drop=True)
    return agg
