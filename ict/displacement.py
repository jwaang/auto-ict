"""Displacement detection — impulsive candles indicating institutional entry.

A displacement candle has a body larger than DISPLACEMENT_ATR_MULT * ATR,
signaling aggressive institutional buying/selling.
"""

import numpy as np
import pandas as pd

from ict.candles import calc_atr, candle_body


def detect_displacements(
    df: pd.DataFrame,
    atr_period: int = 14,
    atr_mult: float = 2.0,
) -> list[dict]:
    """Detect displacement candles (body > mult * ATR).

    Args:
        df: OHLC DataFrame
        atr_period: Period for ATR calculation
        atr_mult: Multiplier threshold (e.g. 2.0 = body must be > 2x ATR)

    Returns:
        List of displacement dicts
    """
    atr = calc_atr(df, atr_period)
    body = candle_body(df)
    timestamps = df["timestamp"].values if "timestamp" in df.columns else range(len(df))

    displacements = []
    opens = df["open"].values
    closes = df["close"].values
    atr_arr = atr.to_numpy()
    body_arr = body.to_numpy()

    # Only bars with a usable ATR can be displacements; compute the ratio for
    # those in one pass and visit just the ones that clear the threshold.
    usable = ~np.isnan(atr_arr) & (atr_arr != 0)
    ratios = np.divide(body_arr, atr_arr, out=np.zeros_like(body_arr, dtype=float), where=usable)
    candidates = np.flatnonzero(usable & (ratios >= atr_mult))

    for i in candidates:
        i = int(i)
        if i < atr_period:
            continue

        direction = "bullish" if closes[i] > opens[i] else "bearish"

        # Count consecutive displacement candles in same direction
        consecutive = 1
        for j in range(i - 1, max(0, i - 5), -1):
            if atr_arr[j] == 0 or np.isnan(atr_arr[j]):
                break
            if body_arr[j] / atr_arr[j] >= atr_mult:
                j_dir = "bullish" if closes[j] > opens[j] else "bearish"
                if j_dir == direction:
                    consecutive += 1
                else:
                    break
            else:
                break

        displacements.append({
            "direction": direction,
            "candle_index": i,
            "timestamp": str(timestamps[i]),
            "body": float(body_arr[i]),
            "atr": float(atr_arr[i]),
            "body_atr_ratio": round(float(ratios[i]), 2),
            "consecutive_count": consecutive,
        })

    return displacements
