"""Liquidity zone detection and sweep identification.

Buy-side liquidity: above swing highs (clusters of short stops).
Sell-side liquidity: below swing lows (clusters of long stops).
"""

import pandas as pd


def detect_liquidity_zones(
    swings: list[dict],
    tolerance: float = 0.002,
) -> list[dict]:
    """Cluster swing highs/lows into liquidity zones.

    Args:
        swings: List of swing dicts from structure.detect_swings()
        tolerance: Price proximity threshold as fraction (0.002 = 0.2%)

    Returns:
        List of liquidity zone dicts
    """
    swing_highs = sorted(
        [s for s in swings if s["type"] == "swing_high"],
        key=lambda s: s["level"],
    )
    swing_lows = sorted(
        [s for s in swings if s["type"] == "swing_low"],
        key=lambda s: s["level"],
    )

    zones = []

    # Cluster swing highs → buy-side liquidity (stops from shorts sit above)
    zones.extend(_cluster_levels(swing_highs, "buy_side", tolerance))

    # Cluster swing lows → sell-side liquidity (stops from longs sit below)
    zones.extend(_cluster_levels(swing_lows, "sell_side", tolerance))

    return zones


def _cluster_levels(
    swings: list[dict],
    liq_type: str,
    tolerance: float,
) -> list[dict]:
    """Group nearby swing levels into clusters."""
    if not swings:
        return []

    clusters: list[list[dict]] = []
    current_cluster = [swings[0]]

    for s in swings[1:]:
        prev_level = current_cluster[-1]["level"]
        if abs(s["level"] - prev_level) / prev_level <= tolerance:
            current_cluster.append(s)
        else:
            clusters.append(current_cluster)
            current_cluster = [s]
    clusters.append(current_cluster)

    zones = []
    for cluster in clusters:
        levels = [s["level"] for s in cluster]
        zones.append({
            "type": liq_type,
            "level": round(sum(levels) / len(levels), 4),
            "touch_count": len(cluster),
            "range_high": max(levels),
            "range_low": min(levels),
            "timestamps": [s["timestamp"] for s in cluster],
            "swept": False,
        })

    return zones


def check_liquidity_sweeps(
    df: pd.DataFrame,
    zones: list[dict],
) -> list[dict]:
    """Check if price has swept (wicked through then reversed) any liquidity zones.

    A sweep occurs when price moves beyond the zone level but closes back
    on the other side, indicating a liquidity grab.
    """
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values

    for zone in zones:
        level = zone["level"]
        for i in range(len(df)):
            if zone["type"] == "buy_side":
                # Buy-side sweep: high exceeds level but close below it
                if highs[i] > level and closes[i] < level:
                    zone["swept"] = True
                    zone["sweep_candle_index"] = i
                    break
            else:
                # Sell-side sweep: low goes below level but close above it
                if lows[i] < level and closes[i] > level:
                    zone["swept"] = True
                    zone["sweep_candle_index"] = i
                    break

    return zones
