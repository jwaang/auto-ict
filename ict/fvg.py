"""Fair Value Gap (FVG) detection.

Bullish FVG: candle[i+2].low > candle[i].high — gap up between candle 1 high and candle 3 low.
Bearish FVG: candle[i+2].high < candle[i].low — gap down between candle 1 low and candle 3 high.
"""

import pandas as pd


def detect_fvgs(df: pd.DataFrame, min_gap_pct: float = 0.0) -> list[dict]:
    """Detect Fair Value Gaps in OHLC data.

    Args:
        df: DataFrame with open, high, low, close, timestamp columns
        min_gap_pct: Minimum gap size as % of price to qualify (filters noise)

    Returns:
        List of FVG dicts with type, top, bottom, midpoint, timestamp, filled status
    """
    fvgs = []
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    timestamps = df["timestamp"].values if "timestamp" in df.columns else range(len(df))

    for i in range(len(df) - 2):
        c1_high = highs[i]
        c1_low = lows[i]
        c3_high = highs[i + 2]
        c3_low = lows[i + 2]
        mid_price = closes[i + 1]

        # Bullish FVG: gap between candle 1 high and candle 3 low
        if c3_low > c1_high:
            gap_size = c3_low - c1_high
            if min_gap_pct > 0 and (gap_size / mid_price) < min_gap_pct:
                continue
            # Check if FVG was filled by subsequent price action
            filled = False
            for j in range(i + 3, len(df)):
                if lows[j] <= c1_high:  # Price traded back into the gap
                    filled = True
                    break
            fvgs.append({
                "type": "bullish",
                "top": float(c3_low),
                "bottom": float(c1_high),
                "midpoint": float((c3_low + c1_high) / 2),
                "gap_size": float(gap_size),
                "candle_index": i + 1,
                "timestamp": str(timestamps[i + 1]),
                "filled": filled,
            })

        # Bearish FVG: gap between candle 1 low and candle 3 high
        if c3_high < c1_low:
            gap_size = c1_low - c3_high
            if min_gap_pct > 0 and (gap_size / mid_price) < min_gap_pct:
                continue
            filled = False
            for j in range(i + 3, len(df)):
                if highs[j] >= c1_low:
                    filled = True
                    break
            fvgs.append({
                "type": "bearish",
                "top": float(c1_low),
                "bottom": float(c3_high),
                "midpoint": float((c1_low + c3_high) / 2),
                "gap_size": float(gap_size),
                "candle_index": i + 1,
                "timestamp": str(timestamps[i + 1]),
                "filled": filled,
            })

    return fvgs


def get_unfilled_fvgs(fvgs: list[dict]) -> list[dict]:
    """Filter to only unfilled FVGs (potential trade targets)."""
    return [f for f in fvgs if not f["filled"]]
