"""Inversion FVG (IFVG) detection.

When price breaks through an FVG entirely, it becomes an Inversion FVG
with flipped polarity:
- Bullish FVG that's fully mitigated → bearish IFVG (now acts as resistance)
- Bearish FVG that's fully mitigated → bullish IFVG (now acts as support)

IFVGs are re-tested levels where the market has shown it can push through,
making the flipped zone a valid entry area.
"""

from __future__ import annotations


def detect_ifvgs(fvgs: list) -> list[dict]:
    """Detect Inversion FVGs from fully mitigated FVGs.

    Args:
        fvgs: All FVGs from smc_adapter (including filled ones)

    Returns:
        List of IFVG dicts with flipped polarity.
    """
    ifvgs = []

    for fvg in fvgs:
        if not fvg.get("filled"):
            continue
        mit_idx = fvg.get("mitigated_index")
        if mit_idx is None:
            continue

        original_type = fvg["type"]
        flipped_type = "bearish" if original_type == "bullish" else "bullish"

        ifvgs.append({
            "type": flipped_type,
            "original_type": original_type,
            "top": fvg["top"],
            "bottom": fvg["bottom"],
            "midpoint": fvg.get("midpoint", (fvg["top"] + fvg["bottom"]) / 2),
            "consequent_encroachment": fvg.get("consequent_encroachment", (fvg["top"] + fvg["bottom"]) / 2),
            "candle_index": fvg["candle_index"],
            "mitigated_index": mit_idx,
        })

    return ifvgs


def get_active_ifvgs(
    ifvgs: list,
    current_price: float,
    atr: float,
) -> list[dict]:
    """Filter to IFVGs near current price (within 2x ATR)."""
    active = []
    for ifvg in ifvgs:
        dist = min(abs(current_price - ifvg["top"]), abs(current_price - ifvg["bottom"]))
        if dist <= atr * 2:
            active.append(ifvg)
    return active
