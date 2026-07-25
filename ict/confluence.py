"""Confluence orchestrator — runs all ICT detectors and scores setups."""

import pandas as pd

from config import (
    ATR_PERIOD,
    CONFLUENCE_WEIGHTS,
    DISPLACEMENT_ATR_MULT,
    LIQUIDITY_CLUSTER_TOLERANCE,
    MIN_CONFLUENCE_SCORE,
    SWING_LOOKBACK,
    USE_SMC_LIBRARY,
)
from ict.candles import calc_atr
from ict.displacement import detect_displacements
from ict.fib import calc_ote_zone, calc_premium_discount, is_in_ote
from ict.killzones import get_active_killzone, get_silver_bullet_window, is_crypto

# Legacy imports (used when USE_SMC_LIBRARY=False)
from ict.fvg import detect_fvgs as legacy_detect_fvgs, get_unfilled_fvgs as legacy_get_unfilled
from ict.liquidity import check_liquidity_sweeps, detect_liquidity_zones
from ict.order_blocks import detect_order_blocks as legacy_detect_obs, get_unmitigated_obs as legacy_get_unmitigated
from ict.structure import detect_structure_breaks, detect_swings as legacy_detect_swings, determine_bias

# SMC library imports (lazy — only loaded when USE_SMC_LIBRARY=True)
# This allows the codebase to run without the smartmoneyconcepts package
# installed when USE_SMC_LIBRARY is set to False.
_smc_adapter = None

def _load_smc_adapter():
    global _smc_adapter
    if _smc_adapter is None:
        from ict import smc_adapter as _mod
        _smc_adapter = _mod
    return _smc_adapter


def analyze_timeframe(df: pd.DataFrame, label: str) -> dict:
    """Run all ICT detectors on a single timeframe DataFrame.

    Returns a dict with all detected ICT levels for this timeframe.
    Uses the SMC library via adapter when USE_SMC_LIBRARY=True,
    falls back to hand-rolled detectors when False.
    """
    atr = calc_atr(df, ATR_PERIOD)

    if USE_SMC_LIBRARY:
        return _analyze_smc(df, label, atr)
    else:
        return _analyze_legacy(df, label, atr)


def _analyze_smc(df: pd.DataFrame, label: str, atr: pd.Series) -> dict:
    """Analysis path using the smartmoneyconcepts library."""
    adapter = _load_smc_adapter()
    ohlc = adapter.prepare_ohlc(df)

    # Core detections via SMC library
    shl_df, swings = adapter.detect_swings(ohlc, label)
    structure_breaks, bias = adapter.detect_bos_choch(ohlc, shl_df)
    fvgs = adapter.detect_fvgs(ohlc)
    obs = adapter.detect_order_blocks(ohlc, shl_df)
    liquidity_zones = adapter.detect_liquidity(ohlc, shl_df)
    retracement = adapter.detect_retracements(ohlc, shl_df)

    # Custom detection (no library equivalent)
    displacements = detect_displacements(df, ATR_PERIOD, DISPLACEMENT_ATR_MULT)

    # Augment library OBs with ATR displacement ratio
    _augment_obs_with_displacement(obs, displacements)

    # Market Structure Shift detection (CHoCH + displacement)
    mss_events = _detect_mss(structure_breaks, displacements)

    # Previous Day/Week High/Low (only on intraday timeframes)
    pdhl = {}
    if label in ("setup", "entry"):
        try:
            pdhl = adapter.detect_previous_high_low(ohlc)
        except Exception:
            pdhl = {}

    # Current price and timestamp
    current_price = float(df["close"].iloc[-1])
    current_ts = df["timestamp"].iloc[-1] if "timestamp" in df.columns else None

    # Premium/Discount from swing range
    swing_highs = [s for s in swings if s["type"] == "swing_high"]
    swing_lows = [s for s in swings if s["type"] == "swing_low"]
    range_high = max(s["level"] for s in swing_highs) if swing_highs else df["high"].max()
    range_low = min(s["level"] for s in swing_lows) if swing_lows else df["low"].min()
    pd_zone = calc_premium_discount(range_high, range_low, current_price)

    # OTE from the most recent completed swing leg
    ote = {"valid": False}
    if len(swings) >= 2:
        ote = _find_ote_from_swings(swings, bias if bias != "neutral" else "bullish")

    # Kill zone + Silver Bullet
    kill_zone = None
    silver_bullet = None
    if current_ts is not None:
        kill_zone = get_active_killzone(current_ts)
        silver_bullet = get_silver_bullet_window(current_ts)

    unfilled_fvgs = adapter.get_unfilled_fvgs(fvgs)
    unmitigated_obs = adapter.get_unmitigated_obs(obs)

    # Power of 3 / Judas Swing (entry/setup TFs only)
    po3 = None
    if label in ("setup", "entry") and current_ts is not None:
        from ict.po3 import detect_po3_setup
        po3 = detect_po3_setup(df, pd.Timestamp(current_ts), bias)

    # Breaker Blocks and Inversion FVGs
    from ict.breaker_blocks import detect_breaker_blocks, get_active_breakers
    from ict.ifvg import detect_ifvgs, get_active_ifvgs
    breaker_blocks = detect_breaker_blocks(obs, liquidity_zones)
    ifvgs = detect_ifvgs(fvgs)
    atr_val = float(atr.iloc[-1]) if not pd.isna(atr.iloc[-1]) else 0
    active_breakers = get_active_breakers(breaker_blocks, current_price, atr_val) if atr_val else []
    active_ifvgs = get_active_ifvgs(ifvgs, current_price, atr_val) if atr_val else []

    return {
        "timeframe": label,
        "current_price": current_price,
        "current_timestamp": str(current_ts) if current_ts else None,
        "atr_current": round(float(atr.iloc[-1]), 4) if not pd.isna(atr.iloc[-1]) else None,
        "bias": bias,
        "swings": swings,
        "structure_breaks": structure_breaks,
        "fvgs": fvgs,
        "unfilled_fvgs": unfilled_fvgs,
        "order_blocks": obs,
        "unmitigated_obs": unmitigated_obs,
        "displacements": displacements,
        "liquidity_zones": liquidity_zones,
        "premium_discount": pd_zone,
        "ote": ote,
        "kill_zone": kill_zone,
        "candle_count": len(df),
        # New fields from SMC library + research
        "previous_high_low": pdhl,
        "retracement": retracement,
        "mss_events": mss_events,
        "silver_bullet": silver_bullet,
        "breaker_blocks": breaker_blocks,
        "active_breakers": active_breakers,
        "ifvgs": ifvgs,
        "active_ifvgs": active_ifvgs,
        "po3": po3,
    }


def _analyze_legacy(df: pd.DataFrame, label: str, atr: pd.Series) -> dict:
    """Analysis path using hand-rolled detectors (original code)."""
    swings = legacy_detect_swings(df, SWING_LOOKBACK)
    structure_breaks = detect_structure_breaks(swings, df)
    bias = determine_bias(structure_breaks)

    fvgs = legacy_detect_fvgs(df)
    obs = legacy_detect_obs(df, ATR_PERIOD, DISPLACEMENT_ATR_MULT)
    displacements = detect_displacements(df, ATR_PERIOD, DISPLACEMENT_ATR_MULT)
    liquidity_zones = detect_liquidity_zones(swings, LIQUIDITY_CLUSTER_TOLERANCE)
    liquidity_zones = check_liquidity_sweeps(df, liquidity_zones)

    current_price = float(df["close"].iloc[-1])
    current_ts = df["timestamp"].iloc[-1] if "timestamp" in df.columns else None

    swing_highs = [s for s in swings if s["type"] == "swing_high"]
    swing_lows = [s for s in swings if s["type"] == "swing_low"]
    range_high = max(s["level"] for s in swing_highs) if swing_highs else df["high"].max()
    range_low = min(s["level"] for s in swing_lows) if swing_lows else df["low"].min()
    pd_zone = calc_premium_discount(range_high, range_low, current_price)

    ote = {"valid": False}
    if len(swings) >= 2:
        ote = _find_ote_from_swings(swings, bias if bias != "neutral" else "bullish")

    kill_zone = None
    silver_bullet = None
    if current_ts is not None:
        kill_zone = get_active_killzone(current_ts)
        silver_bullet = get_silver_bullet_window(current_ts)

    # MSS detection works with legacy breaks too
    mss_events = _detect_mss(structure_breaks, displacements)

    return {
        "timeframe": label,
        "current_price": current_price,
        "current_timestamp": str(current_ts) if current_ts else None,
        "atr_current": round(float(atr.iloc[-1]), 4) if not pd.isna(atr.iloc[-1]) else None,
        "bias": bias,
        "swings": swings,
        "structure_breaks": structure_breaks,
        "fvgs": fvgs,
        "unfilled_fvgs": legacy_get_unfilled(fvgs),
        "order_blocks": obs,
        "unmitigated_obs": legacy_get_unmitigated(obs),
        "displacements": displacements,
        "liquidity_zones": liquidity_zones,
        "premium_discount": pd_zone,
        "ote": ote,
        "kill_zone": kill_zone,
        "candle_count": len(df),
        # New fields (partial support in legacy mode)
        "previous_high_low": {},
        "retracement": {"direction": "neutral", "current_retracement_pct": 0, "deepest_retracement_pct": 0, "in_ote": False},
        "mss_events": mss_events,
        "silver_bullet": silver_bullet,
    }


# ---------------------------------------------------------------------------
# New detection helpers
# ---------------------------------------------------------------------------

def _augment_obs_with_displacement(obs: list, displacements: list):
    """Enrich library OBs with ATR-based displacement ratio.

    For each OB, find the nearest displacement candle after it (within 5 bars)
    in the same direction and attach the ratio. This makes both the library's
    volume-based strength AND our ATR-based strength available.
    """
    for ob in obs:
        ob_idx = ob["candle_index"]
        ob_dir = ob["type"]  # "bullish" or "bearish"
        best_disp = None
        for d in displacements:
            d_idx = d["candle_index"]
            if d_idx >= ob_idx and d_idx <= ob_idx + 5 and d["direction"] == ob_dir:
                if best_disp is None or d_idx < best_disp["candle_index"]:
                    best_disp = d
        if best_disp:
            ob["displacement_body_atr"] = best_disp["body_atr_ratio"]
            ob["displacement_index"] = best_disp["candle_index"]


def _detect_mss(structure_breaks: list, displacements: list) -> list:
    """Detect Market Structure Shifts (MSS) = CHoCH confirmed by displacement.

    The research defines MSS as a causal sequence: sweep -> CHoCH close ->
    displacement/FVG. Displacement must occur ON or AFTER the structure break,
    not before it. A displacement before the break is unrelated momentum and
    should not retroactively qualify the CHoCH as MSS.
    """
    mss = []
    chochs = [b for b in structure_breaks if b["type"] == "CHoCH"]

    for choch in chochs:
        choch_idx = choch["candle_index"]
        for d in displacements:
            # Displacement must be on or after the CHoCH (causal), within 3 bars
            if d["candle_index"] >= choch_idx and d["candle_index"] <= choch_idx + 3 and d["direction"] == choch["direction"]:
                mss.append({
                    "type": "MSS",
                    "direction": choch["direction"],
                    "level": choch["level"],
                    "candle_index": choch_idx,
                    "timestamp": choch["timestamp"],
                    "displacement_ratio": d["body_atr_ratio"],
                })
                break  # One displacement match per CHoCH

    return mss


# ---------------------------------------------------------------------------
# OTE from swings (unchanged logic)
# ---------------------------------------------------------------------------

def _find_ote_from_swings(swings: list, bias: str) -> dict:
    """Find the correct swing leg for OTE calculation.

    ICT OTE measures the retracement of the most recent impulse move:
    - Bearish bias: find last swing_high -> swing_low sequence (the sell-off).
      OTE = where price retraces UP into that leg (61.8-79% from the low).
    - Bullish bias: find last swing_low -> swing_high sequence (the rally).
      OTE = where price retraces DOWN into that leg (61.8-79% from the high).
    """
    if bias == "bearish":
        last_low = None
        for s in reversed(swings):
            if s["type"] == "swing_low" and last_low is None:
                last_low = s
            elif s["type"] == "swing_high" and last_low is not None:
                return calc_ote_zone(s["level"], last_low["level"], "bearish")
    else:
        last_high = None
        for s in reversed(swings):
            if s["type"] == "swing_high" and last_high is None:
                last_high = s
            elif s["type"] == "swing_low" and last_high is not None:
                return calc_ote_zone(last_high["level"], s["level"], "bullish")

    return {"valid": False}


# ---------------------------------------------------------------------------
# ICT Daily Bias Determination
# ---------------------------------------------------------------------------

def bias_factors(
    bias_analysis: dict,
    swing_analysis: dict,
    entry_analysis: dict,
) -> dict:
    """Score each ICT bias factor independently.

    Returns {factor_name: "bullish" | "bearish" | None}, where None means the
    factor abstains. Split out from determine_ict_bias so a factor's vote rate
    can be measured directly — a silently abstaining factor turns an "N of M"
    rule into unanimity without anyone noticing.
    """
    votes: dict[str, str | None] = {}

    # --- Structure direction (BOS/CHoCH on daily, falling back to 4H) ---
    structure = bias_analysis.get("bias", "neutral")
    if structure == "neutral":
        structure = swing_analysis.get("bias", "neutral")
    votes["structure"] = structure if structure in ("bullish", "bearish") else None

    # --- Liquidity draw: which side still holds unbroken external liquidity ---
    votes["liquidity_draw"] = None
    pdhl = entry_analysis.get("previous_high_low", {})
    if pdhl:
        pdh, pdl = pdhl.get("pdh"), pdhl.get("pdl")
        pdh_broken = pdhl.get("pdh_broken", False)
        pdl_broken = pdhl.get("pdl_broken", False)
        current_price = entry_analysis.get("current_price", 0)

        if pdh and not pdh_broken and pdl_broken:
            votes["liquidity_draw"] = "bullish"   # sell side taken, draw above
        elif pdl and not pdl_broken and pdh_broken:
            votes["liquidity_draw"] = "bearish"   # buy side taken, draw below
        elif pdh and pdl and not pdh_broken and not pdl_broken and current_price:
            # Neither taken — the nearer pool is the likelier draw
            if abs(current_price - pdh) < abs(current_price - pdl):
                votes["liquidity_draw"] = "bullish"
            elif abs(current_price - pdl) < abs(current_price - pdh):
                votes["liquidity_draw"] = "bearish"

    # --- Premium / discount position in the dealing range ---
    pd_zone = bias_analysis.get("premium_discount", {})
    if not pd_zone or pd_zone.get("zone") == "neutral":
        pd_zone = swing_analysis.get("premium_discount", {})
    zone = pd_zone.get("zone", "neutral")
    votes["premium_discount"] = (
        "bullish" if zone == "discount" else "bearish" if zone == "premium" else None
    )

    # --- Liquidity raid: which side was taken MOST RECENTLY ---
    # Asking merely "has a side been swept?" across the whole window always
    # answers yes for both — measured at 16 zones a bar with 88% swept — so the
    # factor abstained on every single bar. ICT's question is which raid just
    # happened, so compare the latest sweep on each side.
    zones = entry_analysis.get("liquidity_zones", [])
    last_sell = max(
        (z.get("sweep_candle_index") for z in zones
         if z.get("type") == "sell_side" and z.get("swept") and z.get("sweep_candle_index") is not None),
        default=None,
    )
    last_buy = max(
        (z.get("sweep_candle_index") for z in zones
         if z.get("type") == "buy_side" and z.get("swept") and z.get("sweep_candle_index") is not None),
        default=None,
    )
    if last_sell is not None and (last_buy is None or last_sell > last_buy):
        votes["raid"] = "bullish"    # lows just taken, expect delivery up
    elif last_buy is not None and (last_sell is None or last_buy > last_sell):
        votes["raid"] = "bearish"    # highs just taken, expect delivery down
    else:
        votes["raid"] = None

    return votes


def determine_ict_bias(
    bias_analysis: dict,
    swing_analysis: dict,
    entry_analysis: dict,
) -> str:
    """Determine HTF bias by combining the ICT bias factors.

    Overridable per run via `backtest.params`:
      bias_factors_used  — which factors vote (default all four)
      bias_vote_rule     — "min_votes" (default), "majority" or "plurality"
      bias_min_votes     — threshold for "min_votes" (default 3)

    ICT treats premium/discount as *where* to enter inside an established bias,
    not as *which way* to trade, so dropping it from the vote is the more
    faithful reading. It stays in the default set for continuity and is meant to
    be swept.
    """
    from backtest import params

    votes = bias_factors(bias_analysis, swing_analysis, entry_analysis)
    used = params.get("bias_factors_used", tuple(votes))
    rule = params.get("bias_vote_rule", "min_votes")
    min_votes = params.get("bias_min_votes", 3)

    bullish = sum(1 for f in used if votes.get(f) == "bullish")
    bearish = sum(1 for f in used if votes.get(f) == "bearish")
    structure = votes.get("structure") or "neutral"

    if rule == "plurality":
        # Any margin decides; only a dead heat is neutral.
        if bullish > bearish:
            return "bullish"
        if bearish > bullish:
            return "bearish"
        return "neutral"

    if rule == "majority":
        # More than half the factors that actually voted.
        cast = bullish + bearish
        if cast and bullish * 2 > cast:
            return "bullish"
        if cast and bearish * 2 > cast:
            return "bearish"
        return "neutral"

    # Default: an absolute number of aligned factors, with structure breaking ties.
    if bullish >= min_votes:
        return "bullish"
    if bearish >= min_votes:
        return "bearish"
    if bullish == bearish and bullish > 0:
        return structure
    return "neutral"


# ---------------------------------------------------------------------------
# Multi-timeframe analysis
# ---------------------------------------------------------------------------

def analyze_multi_timeframe(
    dataframes: dict,
    ticker: str = "",
    _cache: dict | None = None,
) -> dict:
    """Run ICT analysis across all timeframes.

    Args:
        dataframes: {label: DataFrame} with timestamp, open, high, low, close, volume
        ticker: Ticker symbol for crypto detection
        _cache: Optional dict for caching per-timeframe results across calls.
                When provided, a timeframe is only re-analyzed if its latest
                bar timestamp has changed. Pass the same dict across calls
                to enable caching (used by the backtest engine for speed).

    Returns:
        Complete ICT context dict ready for AI prompt
    """
    analyses = {}
    for label, df in dataframes.items():
        if df.empty:
            analyses[label] = {}
            continue

        # Cache: skip re-analysis if the latest bar hasn't changed
        if _cache is not None:
            latest_ts = df["timestamp"].iloc[-1] if "timestamp" in df.columns else None
            cache_key = f"{label}_ts"
            cache_result_key = f"{label}_result"
            if _cache.get(cache_key) == latest_ts and cache_result_key in _cache:
                analyses[label] = _cache[cache_result_key]
                continue
            # Miss — analyze and store
            analyses[label] = analyze_timeframe(df, label)
            _cache[cache_key] = latest_ts
            _cache[cache_result_key] = analyses[label]
        else:
            analyses[label] = analyze_timeframe(df, label)

    # HTF bias from full ICT methodology (structure + liquidity + premium/discount + raids)
    htf_bias = determine_ict_bias(
        analyses.get("bias", {}),
        analyses.get("swing", {}),
        analyses.get("entry", {}),
    )

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


# ---------------------------------------------------------------------------
# Confluence detection
# ---------------------------------------------------------------------------

def find_confluences(setup: dict, entry: dict, htf_bias: str) -> list:
    """Find where ICT concepts overlap between timeframes."""
    confluences = []
    if not setup or not entry:
        return confluences

    entry_obs = entry.get("unmitigated_obs", [])
    entry_fvgs = entry.get("unfilled_fvgs", [])

    # FVG + OB overlap on entry timeframe
    for ob in entry_obs:
        for fvg in entry_fvgs:
            if ob["type"] == fvg["type"]:
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

    # OB in OTE zone
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

    # Setup-timeframe OBs aligned with entry-timeframe FVGs
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

    # NEW: Consequent Encroachment at OB midpoint
    for ob in entry_obs:
        for fvg in entry_fvgs:
            ce = fvg.get("consequent_encroachment")
            if ce and ob["midpoint"] != 0:
                if abs(ce - ob["midpoint"]) / abs(ob["midpoint"]) < 0.002:
                    confluences.append({
                        "type": "ce_at_ob",
                        "direction": ob["type"],
                        "ob": ob,
                        "fvg": fvg,
                        "ce_level": ce,
                    })

    # NEW: PDH/PDL as liquidity target aligned with bias
    pdhl = entry.get("previous_high_low", {})
    if pdhl and htf_bias != "neutral":
        if htf_bias == "bullish" and pdhl.get("pdh") and not pdhl.get("pdh_broken"):
            confluences.append({
                "type": "pdh_target",
                "direction": "bullish",
                "level": pdhl["pdh"],
            })
        elif htf_bias == "bearish" and pdhl.get("pdl") and not pdhl.get("pdl_broken"):
            confluences.append({
                "type": "pdl_target",
                "direction": "bearish",
                "level": pdhl["pdl"],
            })

    return confluences


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_setup(
    confluences: list,
    entry: dict,
    htf_bias: str,
    ticker: str = "",
) -> int:
    """Score a setup 0-100 based on ICT concept alignment."""
    score = 0
    w = CONFLUENCE_WEIGHTS

    # HTF bias alignment
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

    # NEW: PDH/PDL proximity — only unbroken levels aligned with HTF bias
    pdhl = entry.get("previous_high_low", {})
    if pdhl and htf_bias != "neutral":
        price = entry.get("current_price", 0)
        atr_val = entry.get("atr_current") or 1
        # Bullish bias targets buy-side liquidity (unbroken highs)
        # Bearish bias targets sell-side liquidity (unbroken lows)
        if htf_bias == "bullish":
            targets = [("pdh", "pdh_broken"), ("pwh", "pwh_broken")]
        else:
            targets = [("pdl", "pdl_broken"), ("pwl", "pwl_broken")]
        for level_key, broken_key in targets:
            level = pdhl.get(level_key)
            if level and not pdhl.get(broken_key, False) and abs(price - level) < 2 * atr_val:
                score += w.get("pdh_pdl_target", 0)
                break

    # NEW: Silver Bullet window (NY AM 10-11 ET gets extra bonus)
    sb = entry.get("silver_bullet")
    if sb:
        score += w.get("silver_bullet_window", 0)
        if sb == "sb_ny_am":
            score += w.get("silver_bullet_ny_am_bonus", 0)

    # NEW: Market Structure Shift
    if entry.get("mss_events"):
        score += w.get("mss_present", 0)

    # NEW: CE at OB confluence
    if any(c["type"] == "ce_at_ob" for c in confluences):
        score += w.get("ce_at_ob", 0)

    # Power of 3 / Judas Swing
    po3 = entry.get("po3")
    if po3 and po3.get("direction") == htf_bias:
        score += w.get("po3_judas_swing", 0)

    # Breaker Block near price aligned with bias
    active_breakers = entry.get("active_breakers", [])
    if htf_bias != "neutral" and active_breakers:
        aligned_breakers = [bb for bb in active_breakers if bb["type"] == htf_bias]
        if aligned_breakers:
            score += w.get("breaker_block", 0)

    # Inversion FVG near price aligned with bias
    active_ifvgs = entry.get("active_ifvgs", [])
    if htf_bias != "neutral" and active_ifvgs:
        aligned_ifvgs = [ifvg for ifvg in active_ifvgs if ifvg["type"] == htf_bias]
        if aligned_ifvgs:
            score += w.get("ifvg_present", 0)

    return min(score, 100)
