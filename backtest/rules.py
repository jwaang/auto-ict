"""Rule-based trade decisions for backtesting.

Replaces the Claude AI call with deterministic ICT rules so backtests
are reproducible and fast. The rules encode the same ICT methodology
that the AI system prompt enforces.
"""

from config import MIN_CONFLUENCE_SCORE, MIN_RR_RATIO
from ict.killzones import is_in_dead_zone, is_in_killzone, is_crypto


def decide_trade(ict_context: dict, min_score: int = MIN_CONFLUENCE_SCORE) -> dict:
    """Make a deterministic trade decision from ICT analysis.

    Encodes the core ICT rules:
    1. HTF bias must not be neutral
    2. Confluence score >= threshold
    3. Entry timeframe must have actionable levels (FVGs or OBs)
    4. Direction must align with HTF bias
    5. SL/TP derived from ICT levels with minimum R:R

    Args:
        ict_context: Full output from confluence.analyze_multi_timeframe()
        min_score: Minimum confluence score to take a trade

    Returns:
        Decision dict compatible with trading/positions.py and risk.py
    """
    score = ict_context.get("confluence_score", 0)
    htf_bias = ict_context.get("htf_bias", "neutral")
    entry_data = ict_context.get("analyses", {}).get("entry", {})
    setup_data = ict_context.get("analyses", {}).get("setup", {})

    # Fallback: if daily bias is neutral (common with limited data),
    # use the 4H (swing) bias which has more granular structure
    if htf_bias == "neutral":
        swing_bias = ict_context.get("analyses", {}).get("swing", {}).get("bias", "neutral")
        if swing_bias != "neutral":
            htf_bias = swing_bias

    no_trade = {
        "decision": "NO_TRADE",
        "reasoning": "",
        "confidence": 0,
        "confluence_score": score,
    }

    # Rule 1: Must have directional bias
    if htf_bias == "neutral":
        no_trade["reasoning"] = "No HTF directional bias"
        return no_trade

    # Rule 2: Kill zone gate (non-crypto only)
    # ICT methodology: only trade during kill zones, never during dead zones
    ticker = ict_context.get("ticker", "")
    if not is_crypto(ticker):
        current_ts = entry_data.get("current_timestamp")
        if current_ts:
            from datetime import datetime
            import pandas as pd
            ts = pd.Timestamp(current_ts)

            if is_in_dead_zone(ts):
                no_trade["reasoning"] = "In dead zone (NY lunch) — reversal traps likely"
                return no_trade

            if not is_in_killzone(ts):
                no_trade["reasoning"] = "Outside kill zone — low probability window"
                return no_trade

    # Rule 3: Confluence threshold
    if score < min_score:
        no_trade["reasoning"] = f"Confluence {score} < {min_score}"
        return no_trade

    # Rule 4: Must have actionable levels on entry TF
    current_price = entry_data.get("current_price", 0)
    if current_price == 0:
        no_trade["reasoning"] = "No current price available"
        return no_trade

    direction = "LONG" if htf_bias == "bullish" else "SHORT"

    # Find entry, SL, TP from ICT levels
    entry_price, stop_loss, take_profit, setup_type, concepts = _find_trade_levels(
        direction, entry_data, setup_data, current_price
    )

    if entry_price is None:
        no_trade["reasoning"] = f"No valid {direction} levels found on entry TF"
        return no_trade

    # Rule 5: Minimum R:R
    risk = abs(entry_price - stop_loss)
    reward = abs(take_profit - entry_price)
    if risk == 0:
        no_trade["reasoning"] = "Zero risk distance"
        return no_trade

    rr = reward / risk
    if rr < MIN_RR_RATIO:
        no_trade["reasoning"] = f"R:R {rr:.1f} < {MIN_RR_RATIO}"
        return no_trade

    return {
        "decision": direction,
        "entry_price": round(entry_price, 2),
        "stop_loss": round(stop_loss, 2),
        "take_profit": round(take_profit, 2),
        "risk_reward_ratio": round(rr, 2),
        "confidence": min(score // 10, 10),
        "reasoning": f"Rule-based {direction}: {setup_type} (score={score})",
        "setup_type": setup_type,
        "htf_bias": htf_bias,
        "ict_concepts_used": concepts,
        "invalidation": f"Price {'below' if direction == 'LONG' else 'above'} SL at {stop_loss:.2f}",
        "confluence_score": score,
    }


def _find_trade_levels(
    direction: str,
    entry_data: dict,
    setup_data: dict,
    current_price: float,
) -> tuple[float | None, float | None, float | None, str, list[str]]:
    """Find entry, SL, TP from ICT levels on the entry timeframe.

    Priority order for entry zones:
    1. FVG+OB overlap (strongest confluence)
    2. Unmitigated OB aligned with bias
    3. Unfilled FVG aligned with bias

    Returns:
        (entry_price, stop_loss, take_profit, setup_type, concepts_used)
    """
    atr = entry_data.get("atr_current") or 0
    if atr == 0:
        return None, None, None, "", []

    obs = entry_data.get("unmitigated_obs", [])
    fvgs = entry_data.get("unfilled_fvgs", [])
    bias_type = "bullish" if direction == "LONG" else "bearish"

    # Filter to bias-aligned levels
    aligned_obs = [ob for ob in obs if ob.get("type") == bias_type]
    aligned_fvgs = [fvg for fvg in fvgs if fvg.get("type") == bias_type]

    concepts = []
    setup_type = ""

    # Strategy 1: FVG+OB overlap
    entry_price, stop_loss = _find_fvg_ob_overlap(direction, aligned_obs, aligned_fvgs, current_price, atr)
    if entry_price:
        setup_type = "FVG+OB overlap"
        concepts = ["FVG", "OB", "confluence"]

    # Strategy 2: OB entry
    if entry_price is None and aligned_obs:
        entry_price, stop_loss = _find_ob_entry(direction, aligned_obs, current_price, atr)
        if entry_price:
            setup_type = "Order Block"
            concepts = ["OB"]

    # Strategy 3: FVG entry
    if entry_price is None and aligned_fvgs:
        entry_price, stop_loss = _find_fvg_entry(direction, aligned_fvgs, current_price, atr)
        if entry_price:
            setup_type = "Fair Value Gap"
            concepts = ["FVG"]

    if entry_price is None:
        return None, None, None, "", []

    # Add other detected concepts
    if entry_data.get("displacements"):
        concepts.append("displacement")
    ote = entry_data.get("ote", {})
    if ote.get("valid"):
        concepts.append("OTE")
    if entry_data.get("kill_zone"):
        concepts.append("kill_zone")
    swept = [z for z in entry_data.get("liquidity_zones", []) if z.get("swept")]
    if swept:
        concepts.append("liquidity_sweep")
    if entry_data.get("mss_events"):
        concepts.append("MSS")

    # Calculate TP using nearest liquidity target or R:R multiple
    take_profit = _find_take_profit(direction, entry_price, stop_loss, entry_data, setup_data)

    return entry_price, stop_loss, take_profit, setup_type, concepts


def _find_fvg_ob_overlap(
    direction: str,
    obs: list,
    fvgs: list,
    current_price: float,
    atr: float,
) -> tuple[float | None, float | None]:
    """Find an entry where an FVG and OB overlap."""
    for ob in obs:
        for fvg in fvgs:
            ob_lo, ob_hi = ob["low"], ob["high"]
            fvg_lo, fvg_hi = fvg["bottom"], fvg["top"]
            # Check overlap
            if ob_lo <= fvg_hi and fvg_lo <= ob_hi:
                overlap_lo = max(ob_lo, fvg_lo)
                overlap_hi = min(ob_hi, fvg_hi)
                midpoint = (overlap_lo + overlap_hi) / 2

                if direction == "LONG" and midpoint < current_price:
                    # Enter at current price (pullback already happened or entering on approach)
                    sl = ob_lo - atr * 0.5
                    return current_price, sl
                elif direction == "SHORT" and midpoint > current_price:
                    sl = ob_hi + atr * 0.5
                    return current_price, sl
    return None, None


def _find_ob_entry(
    direction: str,
    obs: list,
    current_price: float,
    atr: float,
) -> tuple[float | None, float | None]:
    """Find entry from the nearest bias-aligned OB."""
    best = None
    best_dist = float("inf")

    for ob in obs:
        mid = ob.get("midpoint", (ob["low"] + ob["high"]) / 2)
        dist = abs(current_price - mid)
        # OB should be "behind" price (below for LONG, above for SHORT)
        if direction == "LONG" and mid <= current_price and dist < best_dist:
            best = ob
            best_dist = dist
        elif direction == "SHORT" and mid >= current_price and dist < best_dist:
            best = ob
            best_dist = dist

    if best is None:
        # Also consider OBs price is currently inside
        for ob in obs:
            if ob["low"] <= current_price <= ob["high"]:
                best = ob
                break

    if best is None:
        return None, None

    if direction == "LONG":
        sl = best["low"] - atr * 0.5
    else:
        sl = best["high"] + atr * 0.5

    return current_price, sl


def _find_fvg_entry(
    direction: str,
    fvgs: list,
    current_price: float,
    atr: float,
) -> tuple[float | None, float | None]:
    """Find entry from the nearest bias-aligned FVG."""
    best = None
    best_dist = float("inf")

    for fvg in fvgs:
        mid = (fvg["bottom"] + fvg["top"]) / 2
        dist = abs(current_price - mid)
        if direction == "LONG" and mid <= current_price and dist < best_dist:
            best = fvg
            best_dist = dist
        elif direction == "SHORT" and mid >= current_price and dist < best_dist:
            best = fvg
            best_dist = dist

    if best is None:
        for fvg in fvgs:
            if fvg["bottom"] <= current_price <= fvg["top"]:
                best = fvg
                break

    if best is None:
        return None, None

    if direction == "LONG":
        sl = best["bottom"] - atr * 0.5
    else:
        sl = best["top"] + atr * 0.5

    return current_price, sl


def _find_take_profit(
    direction: str,
    entry: float,
    sl: float,
    entry_data: dict,
    setup_data: dict,
) -> float:
    """Find TP from liquidity targets or use default R:R multiple.

    Priority:
    1. Opposite-side liquidity zone (buy-side for LONG, sell-side for SHORT)
    2. PDH/PDL levels
    3. Default 3:1 R:R from entry
    """
    risk = abs(entry - sl)

    # Try liquidity targets
    liq_zones = entry_data.get("liquidity_zones", []) + setup_data.get("liquidity_zones", [])
    for zone in liq_zones:
        level = zone.get("level", 0)
        if direction == "LONG" and zone.get("type") == "buy_side" and level > entry:
            reward = level - entry
            if reward / risk >= MIN_RR_RATIO:
                return round(level, 2)
        elif direction == "SHORT" and zone.get("type") == "sell_side" and level < entry:
            reward = entry - level
            if reward / risk >= MIN_RR_RATIO:
                return round(level, 2)

    # Try PDH/PDL
    pdhl = entry_data.get("previous_high_low", {})
    if direction == "LONG":
        for key in ("pdh", "pwh"):
            level = pdhl.get(key)
            if level and level > entry and (level - entry) / risk >= MIN_RR_RATIO:
                return round(level, 2)
    else:
        for key in ("pdl", "pwl"):
            level = pdhl.get(key)
            if level and level < entry and (entry - level) / risk >= MIN_RR_RATIO:
                return round(level, 2)

    # Default: 3R target
    if direction == "LONG":
        return round(entry + risk * 3, 2)
    else:
        return round(entry - risk * 3, 2)
