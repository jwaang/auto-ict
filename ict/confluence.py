"""Confluence orchestrator — runs all ICT detectors and scores setups."""

import pandas as pd

from config import (
    ATR_PERIOD,
    CONFLUENCE_WEIGHTS,
    DISPLACEMENT_ATR_MULT,
    LIQUIDITY_CLUSTER_TOLERANCE,
    SWING_LOOKBACK,
)
from ict.candles import calc_atr
from ict.displacement import detect_displacements
from ict.fib import calc_ote_zone, calc_premium_discount, is_in_ote
from ict.fvg import detect_fvgs, get_unfilled_fvgs
from ict.killzones import get_active_killzone, is_crypto
from ict.liquidity import check_liquidity_sweeps, detect_liquidity_zones
from ict.order_blocks import detect_order_blocks, get_unmitigated_obs
from ict.structure import detect_structure_breaks, detect_swings, determine_bias


def analyze_timeframe(df: pd.DataFrame, label: str) -> dict:
    """Run all ICT detectors on a single timeframe DataFrame.

    Returns a dict with all detected ICT levels for this timeframe.
    """
    atr = calc_atr(df, ATR_PERIOD)
    swings = detect_swings(df, SWING_LOOKBACK)
    structure_breaks = detect_structure_breaks(swings, df)
    bias = determine_bias(structure_breaks)

    fvgs = detect_fvgs(df)
    obs = detect_order_blocks(df, ATR_PERIOD, DISPLACEMENT_ATR_MULT)
    displacements = detect_displacements(df, ATR_PERIOD, DISPLACEMENT_ATR_MULT)
    liquidity_zones = detect_liquidity_zones(swings, LIQUIDITY_CLUSTER_TOLERANCE)
    liquidity_zones = check_liquidity_sweeps(df, liquidity_zones)

    # Current price
    current_price = float(df["close"].iloc[-1])
    current_ts = df["timestamp"].iloc[-1] if "timestamp" in df.columns else None

    # Premium/Discount from recent swing range
    swing_highs = [s for s in swings if s["type"] == "swing_high"]
    swing_lows = [s for s in swings if s["type"] == "swing_low"]
    range_high = max(s["level"] for s in swing_highs) if swing_highs else df["high"].max()
    range_low = min(s["level"] for s in swing_lows) if swing_lows else df["low"].min()
    pd_zone = calc_premium_discount(range_high, range_low, current_price)

    # OTE from the most recent completed swing leg (the impulse move)
    # For bearish bias: find the last swing high → swing low pair (sell-off leg)
    # For bullish bias: find the last swing low → swing high pair (rally leg)
    # The OTE is where price retraces INTO that leg
    ote = {"valid": False}
    if len(swings) >= 2:
        ote = _find_ote_from_swings(swings, bias if bias != "neutral" else "bullish")

    # Kill zone check
    kill_zone = None
    if current_ts is not None:
        kill_zone = get_active_killzone(current_ts)

    return {
        "timeframe": label,
        "current_price": current_price,
        "current_timestamp": str(current_ts) if current_ts else None,
        "atr_current": round(float(atr.iloc[-1]), 4) if not pd.isna(atr.iloc[-1]) else None,
        "bias": bias,
        "swings": swings,
        "structure_breaks": structure_breaks,
        "fvgs": fvgs,
        "unfilled_fvgs": get_unfilled_fvgs(fvgs),
        "order_blocks": obs,
        "unmitigated_obs": get_unmitigated_obs(obs),
        "displacements": displacements,
        "liquidity_zones": liquidity_zones,
        "premium_discount": pd_zone,
        "ote": ote,
        "kill_zone": kill_zone,
        "candle_count": len(df),
    }


def _find_ote_from_swings(swings: list[dict], bias: str) -> dict:
    """Find the correct swing leg for OTE calculation.

    ICT OTE measures the retracement of the most recent impulse move:
    - Bearish bias: find last swing_high → swing_low sequence (the sell-off).
      OTE = where price retraces UP into that leg (61.8-79% from the low).
    - Bullish bias: find last swing_low → swing_high sequence (the rally).
      OTE = where price retraces DOWN into that leg (61.8-79% from the high).

    The key: the two swings must be sequential (high before low for bearish,
    low before high for bullish) to represent a real impulse leg.
    """
    if bias == "bearish":
        # Walk backwards to find the last swing_high that precedes a swing_low
        last_low = None
        for s in reversed(swings):
            if s["type"] == "swing_low" and last_low is None:
                last_low = s
            elif s["type"] == "swing_high" and last_low is not None:
                # Found: swing_high → swing_low = bearish impulse leg
                return calc_ote_zone(s["level"], last_low["level"], "bearish")
    else:
        # Walk backwards to find the last swing_low that precedes a swing_high
        last_high = None
        for s in reversed(swings):
            if s["type"] == "swing_high" and last_high is None:
                last_high = s
            elif s["type"] == "swing_low" and last_high is not None:
                # Found: swing_low → swing_high = bullish impulse leg
                return calc_ote_zone(last_high["level"], s["level"], "bullish")

    return {"valid": False}


def analyze_multi_timeframe(
    dataframes: dict[str, pd.DataFrame],
    ticker: str = "",
) -> dict:
    """Run ICT analysis across all timeframes.

    Args:
        dataframes: {label: DataFrame} from yahoo.fetch_multi_timeframe()
        ticker: Ticker symbol for crypto detection

    Returns:
        Complete ICT context dict ready for AI prompt
    """
    analyses = {}
    for label, df in dataframes.items():
        analyses[label] = analyze_timeframe(df, label)

    # HTF bias comes from the bias timeframe (daily)
    htf_bias = analyses.get("bias", {}).get("bias", "neutral")

    # Find confluences between setup and entry timeframes
    setup = analyses.get("setup", {})
    entry = analyses.get("entry", {})
    confluences = find_confluences(setup, entry, htf_bias)
    score = score_setup(confluences, entry, htf_bias, ticker)

    # Last 20 entry-timeframe candles for Claude context
    entry_df = dataframes.get("entry", pd.DataFrame())
    recent_candles = []
    if not entry_df.empty:
        tail = entry_df.tail(20)
        for _, row in tail.iterrows():
            recent_candles.append({
                "timestamp": str(row.get("timestamp", "")),
                "open": round(row["open"], 2),
                "high": round(row["high"], 2),
                "low": round(row["low"], 2),
                "close": round(row["close"], 2),
            })

    return {
        "ticker": ticker,
        "htf_bias": htf_bias,
        "analyses": analyses,
        "confluences": confluences,
        "confluence_score": score,
        "recent_entry_candles": recent_candles,
        "is_crypto": is_crypto(ticker),
    }


def find_confluences(setup: dict, entry: dict, htf_bias: str) -> list[dict]:
    """Find where ICT concepts overlap between timeframes."""
    confluences = []
    if not setup or not entry:
        return confluences

    entry_obs = entry.get("unmitigated_obs", [])
    entry_fvgs = entry.get("unfilled_fvgs", [])

    # Check FVG + OB overlap on entry timeframe
    for ob in entry_obs:
        for fvg in entry_fvgs:
            if ob["type"] == fvg["type"]:
                # Check if they overlap in price
                ob_range = (ob["low"], ob["high"])
                fvg_range = (fvg["bottom"], fvg["top"])
                if ob_range[0] <= fvg_range[1] and fvg_range[0] <= ob_range[1]:
                    confluences.append({
                        "type": "fvg_ob_overlap",
                        "direction": ob["type"],
                        "ob": ob,
                        "fvg": fvg,
                        "overlap_high": min(ob["high"], fvg["top"]),
                        "overlap_low": max(ob["low"], fvg["bottom"]),
                    })

    # Check OB in OTE zone
    ote = entry.get("ote", {})
    if ote.get("valid"):
        for ob in entry_obs:
            if is_in_ote(ob["midpoint"], ote):
                confluences.append({
                    "type": "ob_in_ote",
                    "direction": ob["type"],
                    "ob": ob,
                    "ote": ote,
                })

    # Check setup-timeframe OBs that align with entry-timeframe levels
    setup_obs = setup.get("unmitigated_obs", [])
    for s_ob in setup_obs:
        for e_fvg in entry_fvgs:
            if s_ob["type"] == e_fvg["type"]:
                if s_ob["low"] <= e_fvg["top"] and e_fvg["bottom"] <= s_ob["high"]:
                    confluences.append({
                        "type": "htf_ob_ltf_fvg",
                        "direction": s_ob["type"],
                        "setup_ob": s_ob,
                        "entry_fvg": e_fvg,
                    })

    return confluences


def score_setup(
    confluences: list[dict],
    entry: dict,
    htf_bias: str,
    ticker: str = "",
) -> int:
    """Score a setup 0-100 based on ICT concept alignment."""
    score = 0
    w = CONFLUENCE_WEIGHTS

    # HTF bias alignment — check if entry-level signals match HTF direction
    entry_obs = entry.get("unmitigated_obs", [])
    entry_fvgs = entry.get("unfilled_fvgs", [])
    if htf_bias != "neutral":
        aligned_obs = [ob for ob in entry_obs if ob["type"] == htf_bias]
        aligned_fvgs = [f for f in entry_fvgs if f["type"] == htf_bias]
        if aligned_obs or aligned_fvgs:
            score += w["htf_bias_aligned"]

    if entry_fvgs:
        score += w["fvg_present"]
    if entry_obs:
        score += w["ob_present"]

    # FVG+OB overlap
    if any(c["type"] == "fvg_ob_overlap" for c in confluences):
        score += w["fvg_ob_overlap"]

    # OTE
    ote = entry.get("ote", {})
    current_price = entry.get("current_price", 0)
    if ote.get("valid") and is_in_ote(current_price, ote):
        score += w["in_ote_zone"]

    # Displacement
    if entry.get("displacements"):
        score += w["displacement_present"]

    # Liquidity sweep
    swept_zones = [z for z in entry.get("liquidity_zones", []) if z.get("swept")]
    if swept_zones:
        score += w["liquidity_sweep"]

    # Kill zone (skip for crypto)
    if is_crypto(ticker) or entry.get("kill_zone"):
        score += w["in_kill_zone"]

    # Premium/Discount alignment
    pd_zone = entry.get("premium_discount", {})
    zone = pd_zone.get("zone", "neutral")
    if (htf_bias == "bullish" and zone == "discount") or \
       (htf_bias == "bearish" and zone == "premium"):
        score += w["premium_discount_aligned"]

    return min(score, 100)
