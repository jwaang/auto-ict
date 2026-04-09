"""Power of 3 (AMD) / Judas Swing detection.

The ICT Power of 3 framework:
1. Accumulation — Asian session consolidation (midnight-5 AM ET)
2. Manipulation — Judas Swing: false move sweeping one side of the range
3. Distribution — Real move to the day's target

On a bullish day: price drops during manipulation (sweeps Asian low),
then rallies during distribution. On a bearish day: vice versa.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")

# Asian session range: midnight to 5 AM ET
_ASIAN_START_HOUR = 0
_ASIAN_END_HOUR = 5


def detect_asian_range(
    df: pd.DataFrame,
    current_time: pd.Timestamp,
) -> dict | None:
    """Detect the Asian session range for today.

    Finds bars between midnight and 5 AM ET on the same date as current_time,
    and returns their high/low range.

    Returns:
        {"high": float, "low": float, "start_time": ts, "end_time": ts} or None
    """
    if "timestamp" not in df.columns:
        return None

    et_now = current_time.astimezone(_ET)
    # Build today's Asian window in ET
    asian_start = et_now.replace(hour=_ASIAN_START_HOUR, minute=0, second=0, microsecond=0)
    asian_end = et_now.replace(hour=_ASIAN_END_HOUR, minute=0, second=0, microsecond=0)

    # Only valid after Asian session ends
    if et_now.hour < _ASIAN_END_HOUR:
        return None

    # Filter bars in the Asian window
    start_utc = pd.Timestamp(asian_start)
    end_utc = pd.Timestamp(asian_end)
    mask = (df["timestamp"] >= start_utc) & (df["timestamp"] < end_utc)
    asian_bars = df[mask]

    if len(asian_bars) < 3:
        return None

    return {
        "high": float(asian_bars["high"].max()),
        "low": float(asian_bars["low"].min()),
        "start_time": str(asian_bars["timestamp"].iloc[0]),
        "end_time": str(asian_bars["timestamp"].iloc[-1]),
    }


def detect_judas_swing(
    df: pd.DataFrame,
    asian_range: dict,
    current_time: pd.Timestamp,
) -> dict | None:
    """Detect if a Judas Swing (manipulation) occurred after the Asian session.

    A Judas Swing = price sweeps one side of the Asian range then reverses:
    - Sweep above Asian high → bearish Judas (manipulation up, real move down)
    - Sweep below Asian low → bullish Judas (manipulation down, real move up)

    Returns:
        {"type": "bullish"|"bearish", "sweep_level": float, "asian_range": dict} or None
    """
    if "timestamp" not in df.columns:
        return None

    et_now = current_time.astimezone(_ET)
    asian_end = et_now.replace(hour=_ASIAN_END_HOUR, minute=0, second=0, microsecond=0)
    end_utc = pd.Timestamp(asian_end)

    # Only look at bars after Asian session
    post_asian = df[df["timestamp"] >= end_utc]
    if len(post_asian) < 2:
        return None

    asian_high = asian_range["high"]
    asian_low = asian_range["low"]

    # Check for sweeps of the Asian range
    swept_high = post_asian["high"].max() > asian_high
    swept_low = post_asian["low"].min() < asian_low

    if swept_low and not swept_high:
        return {
            "type": "bullish",
            "sweep_level": float(post_asian["low"].min()),
            "asian_range": asian_range,
        }
    elif swept_high and not swept_low:
        return {
            "type": "bearish",
            "sweep_level": float(post_asian["high"].max()),
            "asian_range": asian_range,
        }
    elif swept_high and swept_low:
        # Both swept — ambiguous, check which was first
        first_high_sweep = post_asian[post_asian["high"] > asian_high]
        first_low_sweep = post_asian[post_asian["low"] < asian_low]
        if len(first_high_sweep) > 0 and len(first_low_sweep) > 0:
            if first_high_sweep.index[0] < first_low_sweep.index[0]:
                return {"type": "bearish", "sweep_level": float(first_high_sweep["high"].iloc[0]), "asian_range": asian_range}
            else:
                return {"type": "bullish", "sweep_level": float(first_low_sweep["low"].iloc[0]), "asian_range": asian_range}

    return None


def detect_po3_setup(
    df: pd.DataFrame,
    current_time: pd.Timestamp,
    htf_bias: str,
) -> dict | None:
    """Full Power of 3 detection: Asian range + Judas Swing + bias alignment.

    The Judas direction must align with expected manipulation:
    - Bullish bias: expect bearish manipulation (sweep Asian high) then reversal down? No —
      bullish bias expects BEARISH Judas (sweep below Asian low, then distribution UP).
    - Bearish bias: expect BULLISH Judas (sweep above Asian high, then distribution DOWN).

    Wait — per ICT: Judas Swing is the FALSE move. For a bullish day, the Judas sweeps
    sell-side (below Asian low). The Judas type here represents the REAL direction after
    the false move. So bullish Judas = bullish day = aligned with bullish HTF bias.

    Returns full PO3 context dict or None.
    """
    asian_range = detect_asian_range(df, current_time)
    if asian_range is None:
        return None

    judas = detect_judas_swing(df, asian_range, current_time)
    if judas is None:
        return None

    # Judas type should align with HTF bias (bullish Judas for bullish bias)
    if htf_bias != "neutral" and judas["type"] != htf_bias:
        return None

    return {
        "asian_range": asian_range,
        "judas_swing": judas,
        "phase": "distribution",
        "direction": judas["type"],
    }
