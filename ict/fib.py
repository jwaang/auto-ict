"""Premium/Discount zones and Optimal Trade Entry (OTE) via Fibonacci retracement.

OTE zone: 61.8% - 79% retracement (sweet spot = 70.5%).
Premium: above 50% of range (sell zone).
Discount: below 50% of range (buy zone).
"""

from config import OTE_FIB_LOW, OTE_FIB_HIGH, OTE_FIB_SWEET_SPOT


def calc_premium_discount(
    range_high: float,
    range_low: float,
    current_price: float,
) -> dict:
    """Determine if current price is in premium or discount zone.

    Args:
        range_high: Recent range high (swing high)
        range_low: Recent range low (swing low)
        current_price: Current price

    Returns:
        Dict with zone info
    """
    total_range = range_high - range_low
    if total_range <= 0:
        return {"zone": "neutral", "equilibrium": current_price, "range_high": range_high, "range_low": range_low}

    equilibrium = range_low + total_range * 0.5

    if current_price > equilibrium:
        zone = "premium"
    elif current_price < equilibrium:
        zone = "discount"
    else:
        zone = "equilibrium"

    return {
        "zone": zone,
        "equilibrium": round(equilibrium, 4),
        "range_high": range_high,
        "range_low": range_low,
        "current_price": current_price,
        "position_pct": round((current_price - range_low) / total_range * 100, 1),
    }


def calc_ote_zone(swing_high: float, swing_low: float, direction: str) -> dict:
    """Calculate Optimal Trade Entry zone using Fibonacci retracement.

    For a bullish OTE (buying a pullback in an uptrend):
      - Measure from swing low to swing high
      - OTE zone = retracement between 61.8% and 79% (measured from high)

    For a bearish OTE (selling a pullback in a downtrend):
      - Measure from swing high to swing low
      - OTE zone = retracement between 61.8% and 79% (measured from low)
    """
    total_range = swing_high - swing_low
    if total_range <= 0:
        return {"valid": False}

    if direction == "bullish":
        # Pullback from high — OTE is below equilibrium
        ote_high = swing_high - total_range * OTE_FIB_LOW
        ote_low = swing_high - total_range * OTE_FIB_HIGH
        sweet_spot = swing_high - total_range * OTE_FIB_SWEET_SPOT
    else:
        # Pullback from low — OTE is above equilibrium
        ote_low = swing_low + total_range * OTE_FIB_LOW
        ote_high = swing_low + total_range * OTE_FIB_HIGH
        sweet_spot = swing_low + total_range * OTE_FIB_SWEET_SPOT

    return {
        "valid": True,
        "direction": direction,
        "ote_high": round(ote_high, 4),
        "ote_low": round(ote_low, 4),
        "sweet_spot": round(sweet_spot, 4),
        "swing_high": swing_high,
        "swing_low": swing_low,
        "fib_levels": {
            "0.0": swing_low if direction == "bullish" else swing_high,
            "0.5": round((swing_high + swing_low) / 2, 4),
            "0.618": round(ote_high if direction == "bullish" else ote_low, 4),
            "0.705": round(sweet_spot, 4),
            "0.79": round(ote_low if direction == "bullish" else ote_high, 4),
            "1.0": swing_high if direction == "bullish" else swing_low,
        },
    }


def is_in_ote(price: float, ote: dict) -> bool:
    """Check if price is within OTE zone."""
    if not ote.get("valid"):
        return False
    return ote["ote_low"] <= price <= ote["ote_high"]
