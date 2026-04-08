"""Adapter layer: smartmoneyconcepts library -> dict-based ICT system.

Handles:
  1. DataFrame column normalization (timestamp -> datetime index, lowercase cols)
  2. Calling smc functions with correct dependency order
  3. Converting DataFrame outputs (NaN-based signals) to list-of-dicts
  4. Per-timeframe swing_length tuning
"""

import pandas as pd
import numpy as np
from ict.smc_patched import smc

from config import SMC_SWING_LENGTH

# Runtime override for swing_length (used by backtesting engine)
_swing_length_override: dict | None = None


def set_swing_length_override(override: dict | None):
    """Set a runtime override for SMC swing_length (e.g. for backtesting)."""
    global _swing_length_override
    _swing_length_override = override


def prepare_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize a DataFrame for the SMC library.

    The library requires:
      - Columns: open, high, low, close, volume (lowercase)
      - DatetimeIndex for previous_high_low() and sessions()

    Our DataFrames already have lowercase columns. We set the datetime
    index from the 'timestamp' column when present, and ensure volume exists.
    """
    out = df.copy()
    if "timestamp" in out.columns:
        out = out.set_index("timestamp")
        out.index.name = None
    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index)
    # Ensure volume column exists (some Yahoo data may lack it)
    if "volume" not in out.columns:
        out["volume"] = 0
    return out


def get_swing_length(tf_label: str) -> int:
    """Return the swing_length for a given timeframe label."""
    source = _swing_length_override if _swing_length_override else SMC_SWING_LENGTH
    return source.get(tf_label, 10)


# ---------------------------------------------------------------------------
# Swing Highs / Lows
# ---------------------------------------------------------------------------

def detect_swings(ohlc: pd.DataFrame, tf_label: str) -> tuple:
    """Detect swing highs/lows via SMC library.

    Returns:
        (raw_shl_df, swings_list) -- raw DF needed as input to other smc
        functions, plus the converted list-of-dicts for downstream use.
    """
    swing_length = get_swing_length(tf_label)
    shl = smc.swing_highs_lows(ohlc, swing_length=swing_length)

    swings = []
    for i in range(len(shl)):
        val = shl["HighLow"].iloc[i]
        if pd.isna(val):
            continue
        level = float(shl["Level"].iloc[i])
        ts = str(ohlc.index[i])
        swings.append({
            "type": "swing_high" if int(val) == 1 else "swing_low",
            "level": level,
            "candle_index": i,
            "timestamp": ts,
        })

    return shl, swings


# ---------------------------------------------------------------------------
# BOS / CHoCH + Bias
# ---------------------------------------------------------------------------

def detect_bos_choch(ohlc: pd.DataFrame, shl: pd.DataFrame) -> tuple:
    """Detect BOS/CHoCH and derive market bias.

    Returns:
        (breaks_list, bias_string)
    """
    result = smc.bos_choch(ohlc, shl, close_break=True)

    breaks = []
    for i in range(len(result)):
        bos_val = result["BOS"].iloc[i]
        choch_val = result["CHOCH"].iloc[i]

        if pd.isna(bos_val) and pd.isna(choch_val):
            continue

        if not pd.isna(bos_val):
            break_type = "BOS"
            direction = "bullish" if int(bos_val) == 1 else "bearish"
        else:
            break_type = "CHoCH"
            direction = "bullish" if int(choch_val) == 1 else "bearish"

        level = float(result["Level"].iloc[i]) if not pd.isna(result["Level"].iloc[i]) else 0.0
        broken_idx = int(result["BrokenIndex"].iloc[i]) if not pd.isna(result["BrokenIndex"].iloc[i]) else i

        breaks.append({
            "type": break_type,
            "direction": direction,
            "level": level,
            "previous_level": level,
            "candle_index": i,
            "broken_index": broken_idx,
            "timestamp": str(ohlc.index[i]),
        })

    # Derive bias from last 3 breaks (weighted toward recent)
    bias = "neutral"
    if breaks:
        recent = breaks[-3:]
        bullish = sum(1 for b in recent if b["direction"] == "bullish")
        bearish = sum(1 for b in recent if b["direction"] == "bearish")
        if bullish > bearish:
            bias = "bullish"
        elif bearish > bullish:
            bias = "bearish"

    return breaks, bias


# ---------------------------------------------------------------------------
# Order Blocks
# ---------------------------------------------------------------------------

def detect_order_blocks(ohlc: pd.DataFrame, shl: pd.DataFrame) -> list:
    """Detect order blocks via SMC library.

    Returns list of OB dicts with volume-based strength_pct.
    """
    result = smc.ob(ohlc, shl, close_mitigation=False)

    obs = []
    for i in range(len(result)):
        ob_val = result["OB"].iloc[i]
        if pd.isna(ob_val):
            continue

        top = float(result["Top"].iloc[i])
        bottom = float(result["Bottom"].iloc[i])
        volume = float(result["OBVolume"].iloc[i]) if not pd.isna(result["OBVolume"].iloc[i]) else 0
        mitigated_idx = result["MitigatedIndex"].iloc[i]
        pct = float(result["Percentage"].iloc[i]) if not pd.isna(result["Percentage"].iloc[i]) else 0

        obs.append({
            "type": "bullish" if int(ob_val) == 1 else "bearish",
            "high": top,
            "low": bottom,
            "midpoint": round((top + bottom) / 2, 6),
            "candle_index": i,
            "timestamp": str(ohlc.index[i]),
            "ob_volume": volume,
            "strength_pct": round(pct, 1),
            "mitigated": not pd.isna(mitigated_idx) and int(mitigated_idx) != 0,
            "mitigated_index": int(mitigated_idx) if not pd.isna(mitigated_idx) and int(mitigated_idx) != 0 else None,
            # Compat fields — augmented later by _augment_obs_with_displacement
            "displacement_index": i,
            "displacement_body_atr": 0.0,
        })

    return obs


# ---------------------------------------------------------------------------
# Fair Value Gaps
# ---------------------------------------------------------------------------

def detect_fvgs(ohlc: pd.DataFrame) -> list:
    """Detect Fair Value Gaps via SMC library.

    Adds consequent_encroachment (CE) = midpoint of each FVG.
    """
    result = smc.fvg(ohlc, join_consecutive=False)

    fvgs = []
    for i in range(len(result)):
        fvg_val = result["FVG"].iloc[i]
        if pd.isna(fvg_val):
            continue

        top = float(result["Top"].iloc[i])
        bottom = float(result["Bottom"].iloc[i])
        mitigated_idx = result["MitigatedIndex"].iloc[i]
        filled = not pd.isna(mitigated_idx) and int(mitigated_idx) != 0

        midpoint = round((top + bottom) / 2, 6)
        fvgs.append({
            "type": "bullish" if int(fvg_val) == 1 else "bearish",
            "top": top,
            "bottom": bottom,
            "midpoint": midpoint,
            "gap_size": round(top - bottom, 6),
            "candle_index": i,
            "timestamp": str(ohlc.index[i]),
            "filled": filled,
            "mitigated_index": int(mitigated_idx) if filled else None,
            "consequent_encroachment": midpoint,
        })

    return fvgs


# ---------------------------------------------------------------------------
# Liquidity
# ---------------------------------------------------------------------------

def detect_liquidity(ohlc: pd.DataFrame, shl: pd.DataFrame) -> list:
    """Detect liquidity levels (equal highs/lows) via SMC library."""
    result = smc.liquidity(ohlc, shl, range_percent=0.01)

    zones = []
    for i in range(len(result)):
        liq_val = result["Liquidity"].iloc[i]
        if pd.isna(liq_val):
            continue

        level = float(result["Level"].iloc[i])
        end_idx = int(result["End"].iloc[i]) if not pd.isna(result["End"].iloc[i]) else i
        swept_val = result["Swept"].iloc[i]
        swept = not pd.isna(swept_val) and int(swept_val) != 0

        zones.append({
            "type": "buy_side" if int(liq_val) == 1 else "sell_side",
            "level": round(level, 6),
            "touch_count": 2,  # Library requires min 2 levels in group
            "range_high": round(level * 1.001, 6),
            "range_low": round(level * 0.999, 6),
            "candle_index": i,
            "end_index": end_idx,
            "swept": swept,
            "sweep_candle_index": int(swept_val) if swept else None,
            "timestamps": [str(ohlc.index[i])],
        })

    return zones


# ---------------------------------------------------------------------------
# Previous Day/Week High/Low (NEW concept)
# ---------------------------------------------------------------------------

def detect_previous_high_low(ohlc: pd.DataFrame) -> dict:
    """Detect Previous Day/Week High/Low levels.

    Returns dict with PDH, PDL, PWH, PWL and broken status.
    These are primary liquidity targets in ICT methodology.
    """
    pdhl = {}

    # Previous Day High/Low
    try:
        result_1d = smc.previous_high_low(ohlc, time_frame="1D")
        if len(result_1d) > 0:
            last = len(result_1d) - 1
            pdh = result_1d["PreviousHigh"].iloc[last]
            pdl = result_1d["PreviousLow"].iloc[last]
            pdhl["pdh"] = round(float(pdh), 6) if not pd.isna(pdh) else None
            pdhl["pdl"] = round(float(pdl), 6) if not pd.isna(pdl) else None
            pdhl["pdh_broken"] = bool(result_1d["BrokenHigh"].iloc[last]) if not pd.isna(result_1d["BrokenHigh"].iloc[last]) else False
            pdhl["pdl_broken"] = bool(result_1d["BrokenLow"].iloc[last]) if not pd.isna(result_1d["BrokenLow"].iloc[last]) else False
    except Exception:
        pdhl.update({"pdh": None, "pdl": None, "pdh_broken": False, "pdl_broken": False})

    # Previous Week High/Low
    try:
        result_1w = smc.previous_high_low(ohlc, time_frame="1W")
        if len(result_1w) > 0:
            last = len(result_1w) - 1
            pwh = result_1w["PreviousHigh"].iloc[last]
            pwl = result_1w["PreviousLow"].iloc[last]
            pdhl["pwh"] = round(float(pwh), 6) if not pd.isna(pwh) else None
            pdhl["pwl"] = round(float(pwl), 6) if not pd.isna(pwl) else None
            pdhl["pwh_broken"] = bool(result_1w["BrokenHigh"].iloc[last]) if not pd.isna(result_1w["BrokenHigh"].iloc[last]) else False
            pdhl["pwl_broken"] = bool(result_1w["BrokenLow"].iloc[last]) if not pd.isna(result_1w["BrokenLow"].iloc[last]) else False
    except Exception:
        pdhl.update({"pwh": None, "pwl": None, "pwh_broken": False, "pwl_broken": False})

    return pdhl


# ---------------------------------------------------------------------------
# Retracements
# ---------------------------------------------------------------------------

def detect_retracements(ohlc: pd.DataFrame, shl: pd.DataFrame) -> dict:
    """Get current retracement depth from SMC library.

    Returns dict with direction, current/deepest retracement %, and OTE flag.
    """
    try:
        result = smc.retracements(ohlc, shl)
        if len(result) == 0:
            return {"direction": "neutral", "current_retracement_pct": 0, "deepest_retracement_pct": 0, "in_ote": False}

        last = len(result) - 1
        direction_val = result["Direction"].iloc[last]
        current_ret = result["CurrentRetracement%"].iloc[last]
        deepest_ret = result["DeepestRetracement%"].iloc[last]

        direction = "neutral"
        if not pd.isna(direction_val):
            direction = "bullish" if int(direction_val) == 1 else "bearish" if int(direction_val) == -1 else "neutral"

        current = float(current_ret) if not pd.isna(current_ret) else 0.0
        deepest = float(deepest_ret) if not pd.isna(deepest_ret) else 0.0

        return {
            "direction": direction,
            "current_retracement_pct": round(current, 2),
            "deepest_retracement_pct": round(deepest, 2),
            "in_ote": 61.8 <= abs(current) <= 79.0,
        }
    except Exception:
        return {"direction": "neutral", "current_retracement_pct": 0, "deepest_retracement_pct": 0, "in_ote": False}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_unfilled_fvgs(fvgs: list) -> list:
    """Filter to unfilled FVGs only."""
    return [f for f in fvgs if not f["filled"]]


def get_unmitigated_obs(obs: list) -> list:
    """Filter to unmitigated order blocks only."""
    return [ob for ob in obs if not ob["mitigated"]]
