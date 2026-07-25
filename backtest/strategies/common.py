"""Shared detection logic for ICT setup strategies.

Uses only smc_patched (via smc_adapter) for all detections.
No custom detectors (displacement.py, fib.py, candles.py).
Kill zone time checks from killzones.py are used (pure time math).
"""

from __future__ import annotations

import pandas as pd
from zoneinfo import ZoneInfo

from ict import smc_adapter
from ict.breaker_blocks import detect_breaker_blocks, get_active_breakers
from ict.fib import calc_premium_discount
from ict.ifvg import detect_ifvgs, get_active_ifvgs
from ict.killzones import is_in_killzone, is_in_dead_zone, get_silver_bullet_window

_ET = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Inline ATR (avoids importing ict/candles.py)
# ---------------------------------------------------------------------------

def calc_atr_simple(df: pd.DataFrame, period: int = 14) -> float:
    """Calculate current ATR from a DataFrame with high/low/close columns."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(period, min_periods=1).mean()
    val = atr.iloc[-1]
    return float(val) if pd.notna(val) else 0.0


# ---------------------------------------------------------------------------
# Cached SMC detections
# ---------------------------------------------------------------------------

def run_smc_detections(
    df: pd.DataFrame,
    label: str,
    htf_cache: dict,
) -> dict:
    """Run all smc_adapter detectors on a timeframe, with caching.

    Cache key is the latest bar timestamp — if it hasn't changed since
    the last call, the cached result is returned.
    """
    if df.empty:
        return {}

    latest_ts = df["timestamp"].iloc[-1] if "timestamp" in df.columns else None
    cache_ts_key = f"{label}_ts"
    cache_data_key = f"{label}_det"

    if htf_cache.get(cache_ts_key) == latest_ts and cache_data_key in htf_cache:
        return htf_cache[cache_data_key]

    ohlc = smc_adapter.prepare_ohlc(df)
    shl_df, swings = smc_adapter.detect_swings(ohlc, label)
    breaks, bias = smc_adapter.detect_bos_choch(ohlc, shl_df)
    fvgs = smc_adapter.detect_fvgs(ohlc)
    obs = smc_adapter.detect_order_blocks(ohlc, shl_df)
    liquidity = smc_adapter.detect_liquidity(ohlc, shl_df)
    retracement = smc_adapter.detect_retracements(ohlc, shl_df)

    pdhl = {}
    if label in ("setup", "entry"):
        try:
            pdhl = smc_adapter.detect_previous_high_low(ohlc)
        except Exception:
            pdhl = {}

    # Breaker Blocks and Inversion FVGs
    breakers = detect_breaker_blocks(obs, liquidity)
    ifvgs = detect_ifvgs(fvgs)
    cur_price = float(df["close"].iloc[-1])
    cur_atr = calc_atr_simple(df)

    # Premium/discount over the swing range, and the canonical key names that
    # ict.confluence.bias_factors reads.
    #
    # This module used its own names — `pdhl` for previous_high_low, `liquidity`
    # for liquidity_zones — and never computed premium/discount at all. But
    # get_htf_bias hands these dicts to determine_ict_bias, which looks for the
    # confluence path's names. Three of the four bias factors therefore abstained
    # on every bar, bias was always neutral, and **both ICT strategies could never
    # open a trade**. Measured: 23,564 consecutive declines over 2023, bias neutral
    # on 2,065 of 2,065 kill-zone bars.
    #
    # The old names are kept alongside the new ones so existing readers in
    # ict_2022.py and silver_bullet.py keep working.
    swing_highs = [x for x in swings if x["type"] == "swing_high"]
    swing_lows = [x for x in swings if x["type"] == "swing_low"]
    range_high = max((x["level"] for x in swing_highs), default=float(df["high"].max()))
    range_low = min((x["level"] for x in swing_lows), default=float(df["low"].min()))
    pd_zone = calc_premium_discount(range_high, range_low, cur_price)

    result = {
        "swings": swings,
        "breaks": breaks,
        "bias": bias,
        "fvgs": fvgs,
        "unfilled_fvgs": smc_adapter.get_unfilled_fvgs(fvgs),
        "obs": obs,
        "unmitigated_obs": smc_adapter.get_unmitigated_obs(obs),
        "liquidity": liquidity,
        "liquidity_zones": liquidity,
        "retracement": retracement,
        "pdhl": pdhl,
        "previous_high_low": pdhl,
        "premium_discount": pd_zone,
        "current_price": cur_price,
        "breaker_blocks": breakers,
        "active_breakers": get_active_breakers(breakers, cur_price, cur_atr) if cur_atr else [],
        "ifvgs": ifvgs,
        "active_ifvgs": get_active_ifvgs(ifvgs, cur_price, cur_atr) if cur_atr else [],
    }

    htf_cache[cache_ts_key] = latest_ts
    htf_cache[cache_data_key] = result
    return result


# ---------------------------------------------------------------------------
# HTF Bias
# ---------------------------------------------------------------------------

def get_htf_bias(bias_det: dict, swing_det: dict, entry_det: dict | None = None) -> str:
    """Get HTF directional bias using the full ICT methodology.

    When entry_det is provided, uses the 4-factor ICT bias determination
    (structure + liquidity draw + premium/discount + raid status).
    Otherwise falls back to simple structure-based bias.

    Returns 'bullish', 'bearish', or 'neutral'.
    """
    if entry_det is not None:
        from ict.confluence import determine_ict_bias
        return determine_ict_bias(bias_det, swing_det, entry_det)

    # Simple fallback when entry detections aren't available
    bias = bias_det.get("bias", "neutral")
    if bias != "neutral":
        return bias
    return swing_det.get("bias", "neutral")


# ---------------------------------------------------------------------------
# Temporal Sequence Detection: Sweep -> MSS (CHoCH) -> FVG
# ---------------------------------------------------------------------------

def detect_sweep_mss_fvg_sequence(
    detections: dict,
    direction: str,
    current_idx: int,
    lookback: int = 50,
    window_bounds: tuple[int, int] | None = None,
) -> dict | None:
    """Detect the ICT causal sequence: Sweep -> MSS (CHoCH) -> FVG.

    Args:
        detections: Output from run_smc_detections() for entry TF
        direction: 'bullish' or 'bearish'
        current_idx: Current bar index in the entry DataFrame
        lookback: Max bars to look back for the sweep
        window_bounds: Optional (start_idx, end_idx) for a Silver Bullet window.
                       Which parts of the sequence it constrains is set by the
                       `sb_window_scope` override — see below.

    Returns:
        Dict with {sweep, mss, fvg, ob} if found, or None.

    On the window scope. Confining the *whole* chain to one hour makes Silver
    Bullet arithmetically impossible rather than selective: the window holds 4 bars
    at 15m and 12 at 5m, while a CHoCH alone needs a swing to form, confirm and then
    break — roughly 15 bars at swing_length 5. Measured, that produced zero trades
    over a full year at both timeframes, and 220 of 220 in-window directional bars
    failed to find a sequence.

    Research describes the actual rule as the *first FVG formed inside the window*,
    aligned with HTF bias and an MSS. So three readings are available:

        "all"      every leg in-window (the original, and impossible)
        "mss_fvg"  MSS and FVG in-window, the sweep may precede it
        "fvg"      only the FVG in-window, the loosest reading
    """
    from backtest import params

    liquidity = detections.get("liquidity", [])
    breaks = detections.get("breaks", [])
    fvgs = detections.get("unfilled_fvgs", [])
    obs = detections.get("unmitigated_obs", [])

    scope = params.get("sb_window_scope", "all")
    min_idx = current_idx - lookback
    window_start = window_end = None
    if window_bounds:
        window_start, window_end = window_bounds
        if scope == "all":
            min_idx = max(min_idx, window_start)

    current_idx_limit = current_idx

    def _in_window(idx: int, leg: str) -> bool:
        """Whether a leg must sit inside the Silver Bullet window."""
        if window_bounds is None:
            return True
        constrained = {
            "all": ("sweep", "mss", "fvg"),
            "mss_fvg": ("mss", "fvg"),
            "fvg": ("fvg",),
        }.get(scope, ("sweep", "mss", "fvg"))
        if leg not in constrained:
            return True
        return window_start <= idx <= window_end

    # Step 1: Find swept liquidity zones
    sweep_type = "sell_side" if direction == "bullish" else "buy_side"
    sweeps = [
        z for z in liquidity
        if z.get("type") == sweep_type
        and z.get("swept")
        and z.get("sweep_candle_index") is not None
        and min_idx <= z["sweep_candle_index"] <= current_idx_limit
        and _in_window(z["sweep_candle_index"], "sweep")
    ]
    # Most recent sweep first
    sweeps.sort(key=lambda z: z["sweep_candle_index"], reverse=True)

    for sweep in sweeps:
        sweep_idx = sweep["sweep_candle_index"]

        # Step 2: Find CHoCH AFTER the sweep (MSS confirmation)
        qualifying_chochs = [
            b for b in breaks
            if b.get("type") == "CHoCH"
            and b.get("direction") == direction
            and b["candle_index"] > sweep_idx
            and b["candle_index"] <= current_idx_limit
            and _in_window(b["candle_index"], "mss")
        ]
        if not qualifying_chochs:
            continue

        mss = min(qualifying_chochs, key=lambda b: b["candle_index"])

        # Step 3: Find FVG AFTER the CHoCH
        qualifying_fvgs = [
            f for f in fvgs
            if f.get("type") == direction
            and f["candle_index"] > mss["candle_index"]
            and f["candle_index"] <= current_idx_limit
            and _in_window(f["candle_index"], "fvg")
        ]
        if not qualifying_fvgs:
            continue

        entry_fvg = min(qualifying_fvgs, key=lambda f: f["candle_index"])

        # Step 4: Optionally find OB after CHoCH
        qualifying_obs = [
            ob for ob in obs
            if ob.get("type") == direction
            and ob["candle_index"] >= mss["candle_index"]
            and ob["candle_index"] <= current_idx_limit
        ]
        entry_ob = min(qualifying_obs, key=lambda o: o["candle_index"]) if qualifying_obs else None

        return {
            "sweep": sweep,
            "mss": mss,
            "fvg": entry_fvg,
            "ob": entry_ob,
        }

    return None


# ---------------------------------------------------------------------------
# Entry price selection
# ---------------------------------------------------------------------------

def get_entry_price(
    sequence: dict,
    direction: str,
    current_price: float,
) -> tuple[float, str] | tuple[None, None]:
    """Determine entry price from the FVG CE or OB proximal line.

    Entry conditions:
    - Price is inside the FVG zone, OR
    - Price has retraced through the FVG (for LONG: price came down into/through
      the FVG; for SHORT: price came up into/through the FVG). We accept price
      within a small buffer beyond the FVG since in backtesting the bar-by-bar
      evaluation may miss the exact moment price is inside a thin FVG.
    - Alternatively, price is inside an OB zone from the sequence.

    Returns:
        (entry_price, entry_type) or (None, None)
    """
    fvg = sequence["fvg"]
    fvg_top = fvg["top"]
    fvg_bottom = fvg["bottom"]
    fvg_size = fvg_top - fvg_bottom
    ce = fvg.get("consequent_encroachment", (fvg_top + fvg_bottom) / 2)

    # Buffer: allow price slightly beyond FVG (up to 1x FVG size or 2 points)
    buffer = max(fvg_size, 2.0)

    # Check if price is within or near FVG zone
    if fvg_bottom - buffer <= current_price <= fvg_top + buffer:
        if direction == "bullish" and current_price <= fvg_top + buffer:
            return current_price, "FVG_CE"
        elif direction == "bearish" and current_price >= fvg_bottom - buffer:
            return current_price, "FVG_CE"

    # Check if price is within OB zone
    ob = sequence.get("ob")
    if ob:
        ob_buffer = max((ob["high"] - ob["low"]), 2.0)
        if ob["low"] - ob_buffer <= current_price <= ob["high"] + ob_buffer:
            if direction == "bullish" and current_price <= ob["high"] + ob_buffer:
                return current_price, "OB_entry"
            elif direction == "bearish" and current_price >= ob["low"] - ob_buffer:
                return current_price, "OB_entry"

    # Price has moved past the FVG/OB — the sweep->MSS->FVG sequence is
    # confirmed, so enter at market. This is the "aggressive" entry from
    # the docs: the setup is valid, price just moved through the zone
    # faster than our evaluation interval.
    if direction == "bullish" and current_price > fvg_top:
        return current_price, "market_post_FVG"
    elif direction == "bearish" and current_price < fvg_bottom:
        return current_price, "market_post_FVG"

    return None, None


# ---------------------------------------------------------------------------
# Stop loss and take profit
# ---------------------------------------------------------------------------

def calc_stop_loss(
    direction: str,
    sweep: dict,
    atr: float,
    ticker: str = "",
) -> float:
    """SL beyond the sweep extreme + ATR buffer (per-asset multiplier)."""
    from config import SL_ATR_MULTIPLIER
    sl_mult = SL_ATR_MULTIPLIER.get(ticker.upper(), SL_ATR_MULTIPLIER.get("default", 0.5))
    level = sweep["level"]
    buffer = atr * sl_mult

    if direction == "bullish":
        # Long: SL below sweep low
        return round(level - buffer, 2)
    else:
        # Short: SL above sweep high
        return round(level + buffer, 2)


def find_take_profit(
    direction: str,
    entry_price: float,
    stop_loss: float,
    detections: dict,
    default_rr: float = 3.0,
) -> float:
    """Find TP from opposing liquidity or default R multiple.

    Priority:
    1. Opposing liquidity pool (buy-side for LONG, sell-side for SHORT)
    2. PDH/PDL aligned with direction
    3. Default R:R multiple
    """
    risk = abs(entry_price - stop_loss)
    min_tp_dist = risk * 1.0  # at minimum 1R away (nearest valid target)

    # Try opposing liquidity zones
    liquidity = detections.get("liquidity", [])
    target_type = "buy_side" if direction == "bullish" else "sell_side"
    candidates = []

    for zone in liquidity:
        if zone.get("type") != target_type:
            continue
        level = zone["level"]
        if direction == "bullish" and level > entry_price:
            dist = level - entry_price
            if dist >= min_tp_dist:
                candidates.append(level)
        elif direction == "bearish" and level < entry_price:
            dist = entry_price - level
            if dist >= min_tp_dist:
                candidates.append(level)

    if candidates:
        # Nearest qualifying target
        candidates.sort(key=lambda l: abs(l - entry_price))
        return round(candidates[0], 2)

    # Try PDH/PDL
    pdhl = detections.get("pdhl", {})
    if direction == "bullish":
        for key in ("pdh", "pwh"):
            level = pdhl.get(key)
            if level and level > entry_price:
                if abs(level - entry_price) >= min_tp_dist:
                    return round(level, 2)
    else:
        for key in ("pdl", "pwl"):
            level = pdhl.get(key)
            if level and level < entry_price:
                if abs(entry_price - level) >= min_tp_dist:
                    return round(level, 2)

    # Default: R:R multiple
    if direction == "bullish":
        return round(entry_price + risk * default_rr, 2)
    else:
        return round(entry_price - risk * default_rr, 2)


# ---------------------------------------------------------------------------
# Universal Entry Criteria Checklist
# ---------------------------------------------------------------------------

def check_entry_criteria(
    htf_bias: str,
    direction: str,
    sequence: dict,
    entry_det: dict,
    current_price: float,
    current_time: pd.Timestamp,
    ticker: str,
    in_kill_zone: bool,
) -> tuple[bool, str]:
    """Verify the 7-item Universal Entry Criteria Checklist.

    Returns (passed, rejection_reason).
    """
    # 1. HTF bias confirmed
    if htf_bias == "neutral":
        return False, "No HTF directional bias"

    # 2. Trading during a kill zone
    if not in_kill_zone:
        return False, "Outside kill zone"

    # 3. Liquidity has been swept (guaranteed by sequence detection)
    # 4. Displacement occurred (FVG existence = displacement per docs)
    # 5. MSS confirmed on entry TF (CHoCH in sequence)
    # Items 3-5 are guaranteed by detect_sweep_mss_fvg_sequence returning non-None

    # 6. Entry on PD array (FVG/OB) — verified by get_entry_price() in the
    #    calling strategy. We don't duplicate the check here since the
    #    strategy's entry price logic handles buffer/proximity.

    # OTE zone check (from smc_patched retracements) — informational only.
    # The sweep->MSS->FVG sequence is the primary confirmation.
    # OTE adds confluence but is not required.

    # 7. Min R:R is checked by the calling strategy (strategy-specific)

    return True, ""


# ---------------------------------------------------------------------------
# Build decision dict
# ---------------------------------------------------------------------------

def build_decision(
    direction: str,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    htf_bias: str,
    setup_type: str,
    entry_type: str,
    sequence: dict,
    in_ote: bool,
) -> dict:
    """Build a decision dict compatible with validate_trade/positions.py."""
    risk = abs(entry_price - stop_loss)
    reward = abs(take_profit - entry_price)
    rr = round(reward / risk, 2) if risk > 0 else 0

    dir_str = "LONG" if direction == "bullish" else "SHORT"

    concepts = ["liquidity_sweep", "CHoCH", "FVG"]
    if sequence.get("ob"):
        concepts.append("OB")
    if in_ote:
        concepts.append("OTE")

    sweep_level = sequence["sweep"]["level"]
    mss_level = sequence["mss"]["level"]

    return {
        "decision": dir_str,
        "entry_price": round(entry_price, 2),
        "stop_loss": round(stop_loss, 2),
        "take_profit": round(take_profit, 2),
        "risk_reward_ratio": rr,
        "confidence": 8,
        "reasoning": (
            f"{setup_type}: sweep {sequence['sweep']['type']} @{sweep_level:.2f} "
            f"-> CHoCH @{mss_level:.2f} -> {entry_type} entry @{entry_price:.2f}"
        ),
        "setup_type": setup_type,
        "htf_bias": htf_bias,
        "ict_concepts_used": concepts,
        "invalidation": f"Price {'below' if dir_str == 'LONG' else 'above'} SL at {stop_loss:.2f}",
        "confluence_score": 0,
    }
