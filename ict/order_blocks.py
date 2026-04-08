"""Order Block (OB) detection.

Bullish OB: the last bearish candle before a bullish displacement.
Bearish OB: the last bullish candle before a bearish displacement.
"""

import numpy as np
import pandas as pd

from ict.candles import calc_atr, candle_body


def detect_order_blocks(
    df: pd.DataFrame,
    atr_period: int = 14,
    atr_mult: float = 2.0,
    lookback: int = 5,
) -> list[dict]:
    """Detect Order Blocks based on displacement candles.

    Args:
        df: OHLC DataFrame
        atr_period: ATR calculation period
        atr_mult: Body > mult * ATR = displacement
        lookback: How many candles back to search for the opposing candle

    Returns:
        List of OB dicts with type, high, low, midpoint, timestamp, mitigated status
    """
    atr = calc_atr(df, atr_period)
    body = candle_body(df)
    opens = df["open"].values
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    timestamps = df["timestamp"].values if "timestamp" in df.columns else range(len(df))

    obs = []

    for i in range(atr_period, len(df)):
        if atr.iloc[i] is None or np.isnan(atr.iloc[i]) or atr.iloc[i] == 0:
            continue

        ratio = body.iloc[i] / atr.iloc[i]
        if ratio < atr_mult:
            continue

        is_bull_disp = closes[i] > opens[i]

        # Search backwards for the last opposing candle
        for j in range(i - 1, max(0, i - lookback - 1), -1):
            if is_bull_disp and closes[j] < opens[j]:
                # Found bearish candle before bullish displacement → Bullish OB
                mitigated = _check_mitigated(df, j, "bullish", i)
                obs.append({
                    "type": "bullish",
                    "high": float(highs[j]),
                    "low": float(lows[j]),
                    "midpoint": float((highs[j] + lows[j]) / 2),
                    "candle_index": j,
                    "timestamp": str(timestamps[j]),
                    "displacement_index": i,
                    "displacement_body_atr": round(float(ratio), 2),
                    "mitigated": mitigated,
                })
                break
            elif not is_bull_disp and closes[j] > opens[j]:
                # Found bullish candle before bearish displacement → Bearish OB
                mitigated = _check_mitigated(df, j, "bearish", i)
                obs.append({
                    "type": "bearish",
                    "high": float(highs[j]),
                    "low": float(lows[j]),
                    "midpoint": float((highs[j] + lows[j]) / 2),
                    "candle_index": j,
                    "timestamp": str(timestamps[j]),
                    "displacement_index": i,
                    "displacement_body_atr": round(float(ratio), 2),
                    "mitigated": mitigated,
                })
                break

    return obs


def _check_mitigated(df: pd.DataFrame, ob_index: int, ob_type: str, start_from: int) -> bool:
    """Check if an OB has been mitigated (price returned and traded through it)."""
    highs = df["high"].values
    lows = df["low"].values
    ob_high = highs[ob_index]
    ob_low = lows[ob_index]

    for k in range(start_from + 1, len(df)):
        if ob_type == "bullish" and lows[k] <= ob_low:
            return True
        if ob_type == "bearish" and highs[k] >= ob_high:
            return True
    return False


def get_unmitigated_obs(obs: list[dict]) -> list[dict]:
    """Filter to only unmitigated OBs (still valid for entries)."""
    return [ob for ob in obs if not ob["mitigated"]]
