"""Breaker Block detection.

A Breaker Block forms when an Order Block is mitigated (price breaks through it),
AND a liquidity sweep preceded the break. The violated OB flips polarity:
- Bullish OB that gets broken → bearish Breaker Block (resistance)
- Bearish OB that gets broken → bullish Breaker Block (support)

Breaker Blocks are higher-probability than standard OBs because they involve
a confirmed liquidity sweep + failed OB + aggressive reversal.
"""

from __future__ import annotations


def detect_breaker_blocks(obs: list, liquidity_zones: list) -> list[dict]:
    """Detect Breaker Blocks from mitigated OBs + nearby liquidity sweeps.

    Args:
        obs: All OBs from smc_adapter (including mitigated ones)
        liquidity_zones: All liquidity zones from smc_adapter

    Returns:
        List of Breaker Block dicts with flipped polarity.
    """
    breakers = []

    for ob in obs:
        if not ob.get("mitigated"):
            continue
        mit_idx = ob.get("mitigated_index")
        if mit_idx is None:
            continue

        ob_idx = ob["candle_index"]
        ob_type = ob["type"]  # "bullish" or "bearish"

        # Look for a liquidity sweep near the OB before mitigation
        # Bullish OB gets broken → sell-side liquidity was swept first
        # Bearish OB gets broken → buy-side liquidity was swept first
        sweep_type = "sell_side" if ob_type == "bullish" else "buy_side"

        has_sweep = False
        for zone in liquidity_zones:
            if zone.get("type") != sweep_type:
                continue
            if not zone.get("swept"):
                continue
            sweep_idx = zone.get("sweep_candle_index")
            if sweep_idx is None:
                continue
            # Sweep must be near the OB (within 20 bars before or at the OB)
            if ob_idx - 20 <= sweep_idx <= mit_idx:
                has_sweep = True
                break

        if not has_sweep:
            continue

        # Flip polarity
        flipped_type = "bearish" if ob_type == "bullish" else "bullish"

        breakers.append({
            "type": flipped_type,
            "original_type": ob_type,
            "high": ob["high"],
            "low": ob["low"],
            "midpoint": ob.get("midpoint", (ob["high"] + ob["low"]) / 2),
            "candle_index": ob_idx,
            "mitigated_index": mit_idx,
        })

    return breakers


def get_active_breakers(
    breakers: list,
    current_price: float,
    atr: float,
) -> list[dict]:
    """Filter to Breaker Blocks near current price (within 2x ATR)."""
    active = []
    for bb in breakers:
        dist = min(abs(current_price - bb["high"]), abs(current_price - bb["low"]))
        if dist <= atr * 2:
            active.append(bb)
    return active
