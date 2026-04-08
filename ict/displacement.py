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

    for i in range(atr_period, len(df)):
        if atr.iloc[i] is None or np.isnan(atr.iloc[i]) or atr.iloc[i] == 0:
            continue

        body_val = body.iloc[i]
        atr_val = atr.iloc[i]
        ratio = body_val / atr_val

        if ratio >= atr_mult:
            direction = "bullish" if closes[i] > opens[i] else "bearish"

            # Count consecutive displacement candles in same direction
            consecutive = 1
            for j in range(i - 1, max(0, i - 5), -1):
                if body.iloc[j] / atr.iloc[j] >= atr_mult:
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
                "body": float(body_val),
                "atr": float(atr_val),
                "body_atr_ratio": round(float(ratio), 2),
                "consecutive_count": consecutive,
            })

    return displacements
