"""Market Structure: swing highs/lows, BOS (Break of Structure), CHoCH (Change of Character)."""

import numpy as np
import pandas as pd


def detect_swings(df: pd.DataFrame, lookback: int = 5) -> list[dict]:
    """Detect swing highs and swing lows.

    A swing high: bar whose high is greater than all bars within lookback on both sides.
    A swing low: bar whose low is less than all bars within lookback on both sides.
    """
    highs = df["high"].values
    lows = df["low"].values
    timestamps = df["timestamp"].values if "timestamp" in df.columns else range(len(df))

    swings = []

    for i in range(lookback, len(df) - lookback):
        left_highs = highs[i - lookback:i]
        right_highs = highs[i + 1:i + lookback + 1]
        if highs[i] > np.max(left_highs) and highs[i] > np.max(right_highs):
            swings.append({
                "type": "swing_high",
                "level": float(highs[i]),
                "candle_index": i,
                "timestamp": str(timestamps[i]),
            })

        left_lows = lows[i - lookback:i]
        right_lows = lows[i + 1:i + lookback + 1]
        if lows[i] < np.min(left_lows) and lows[i] < np.min(right_lows):
            swings.append({
                "type": "swing_low",
                "level": float(lows[i]),
                "candle_index": i,
                "timestamp": str(timestamps[i]),
            })

    swings.sort(key=lambda s: s["candle_index"])
    return swings


def detect_structure_breaks(swings: list[dict], df: pd.DataFrame) -> list[dict]:
    """Detect BOS and CHoCH from swing sequence.

    BOS (Break of Structure): price breaks a swing point in the direction of the current trend.
    CHoCH (Change of Character): price breaks a swing point against the current trend.
    """
    if len(swings) < 3:
        return []

    breaks = []
    highs = df["high"].values
    lows = df["low"].values
    timestamps = df["timestamp"].values if "timestamp" in df.columns else range(len(df))

    # Determine trend from swing sequence
    trend = "neutral"  # Start neutral

    swing_highs = [s for s in swings if s["type"] == "swing_high"]
    swing_lows = [s for s in swings if s["type"] == "swing_low"]

    for i in range(1, len(swings)):
        current = swings[i]
        # Find the most recent swing of the opposite type
        if current["type"] == "swing_high":
            # Look for previous swing highs
            prev_highs = [s for s in swing_highs if s["candle_index"] < current["candle_index"]]
            if not prev_highs:
                continue
            prev_high = prev_highs[-1]

            # Check if this swing high breaks the previous one
            if current["level"] > prev_high["level"]:
                # Higher high
                if trend == "bearish":
                    break_type = "CHoCH"
                else:
                    break_type = "BOS"
                trend = "bullish"
            else:
                # Lower high
                if trend == "bullish":
                    break_type = "CHoCH"
                    trend = "bearish"
                else:
                    continue

            breaks.append({
                "type": break_type,
                "direction": "bullish" if current["level"] > prev_high["level"] else "bearish",
                "level": current["level"],
                "previous_level": prev_high["level"],
                "candle_index": current["candle_index"],
                "timestamp": current["timestamp"],
            })

        elif current["type"] == "swing_low":
            prev_lows = [s for s in swing_lows if s["candle_index"] < current["candle_index"]]
            if not prev_lows:
                continue
            prev_low = prev_lows[-1]

            if current["level"] < prev_low["level"]:
                # Lower low
                if trend == "bullish":
                    break_type = "CHoCH"
                else:
                    break_type = "BOS"
                trend = "bearish"
            else:
                # Higher low
                if trend == "bearish":
                    break_type = "CHoCH"
                    trend = "bullish"
                else:
                    continue

            breaks.append({
                "type": break_type,
                "direction": "bearish" if current["level"] < prev_low["level"] else "bullish",
                "level": current["level"],
                "previous_level": prev_low["level"],
                "candle_index": current["candle_index"],
                "timestamp": current["timestamp"],
            })

    return breaks


def determine_bias(structure_breaks: list[dict]) -> str:
    """Determine overall market bias from structure breaks.

    Returns "bullish", "bearish", or "neutral".
    """
    if not structure_breaks:
        return "neutral"

    # Weight recent breaks more heavily
    recent = structure_breaks[-3:]
    bullish = sum(1 for b in recent if b["direction"] == "bullish")
    bearish = sum(1 for b in recent if b["direction"] == "bearish")

    if bullish > bearish:
        return "bullish"
    elif bearish > bullish:
        return "bearish"
    return "neutral"
