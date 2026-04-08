"""Multi-timeframe confirmation for conditional entries.

ICT confirmation is top-down — higher timeframe zones require higher timeframe
confirmation. A 4H OB needs at least a 1H reaction, not just 15M noise.

Zone TF → Confirmation TF:
  4H zone → 1H confirmation (strong)
  1H zone → 15M confirmation (standard)
  15M zone → 15M candle reaction (minimum)

Confirmation signals (weighted by strength):
  - CHoCH: Market structure shift in trade direction (strongest)
  - Displacement: Impulsive candle >2x ATR in trade direction (strong)
  - Rejection wick: Long wick showing rejection from zone (moderate)
  - FVG formation: New FVG in trade direction within zone (moderate)
  - BOS: Break of structure continuing trend (supporting)
"""

import pandas as pd

from ict.candles import calc_atr, candle_body
from ict.fvg import detect_fvgs
from ict.structure import detect_swings, detect_structure_breaks
from ict.displacement import detect_displacements

# Confirmation thresholds scale with zone timeframe
CONFIRMATION_THRESHOLDS = {
    "4h": {"min_strong": 1, "min_total": 1, "swing_lookback": 5, "atr_mult": 2.0},
    "1h": {"min_strong": 1, "min_total": 1, "swing_lookback": 4, "atr_mult": 1.8},
    "15m": {"min_strong": 0, "min_total": 2, "swing_lookback": 3, "atr_mult": 1.5},
}

# Signal strength scores — used to weight confirmation quality
SIGNAL_WEIGHTS = {
    "CHoCH": 3,
    "displacement": 3,
    "BOS": 2,
    "rejection_wick": 1,
    "fvg_formation": 1,
}

# Minimum weighted score needed for confirmation at each zone TF
MIN_CONFIRMATION_SCORE = {
    "4h": 3,   # Need at least one strong signal (CHoCH or displacement)
    "1h": 2,   # Need a strong signal or two moderate ones
    "15m": 2,  # Two moderate signals or one strong
}


def check_confirmation(
    df: pd.DataFrame,
    direction: str,
    zone_low: float,
    zone_high: float,
    zone_timeframe: str = "1h",
    lookback_bars: int = 15,
) -> dict:
    """Check if the confirmation timeframe shows entry signals at the zone.

    Args:
        df: Confirmation TF DataFrame (e.g. 1H candles for a 4H zone)
        direction: "bullish" or "bearish"
        zone_low: Bottom of the entry zone
        zone_high: Top of the entry zone
        zone_timeframe: The TF the zone came from ("4h", "1h", "15m")
        lookback_bars: How many recent bars to check

    Returns:
        Dict with confirmed, signals, weighted score, and suggested entry
    """
    if len(df) < 10:
        return {"confirmed": False, "reason": "Insufficient data", "signals": [], "score": 0}

    thresholds = CONFIRMATION_THRESHOLDS.get(zone_timeframe, CONFIRMATION_THRESHOLDS["1h"])
    min_score = MIN_CONFIRMATION_SCORE.get(zone_timeframe, 2)
    signals = []

    # 1. Market structure: CHoCH and BOS
    swings = detect_swings(df, lookback=thresholds["swing_lookback"])
    breaks = detect_structure_breaks(swings, df)
    recent_breaks = [b for b in breaks if b["candle_index"] >= len(df) - lookback_bars]

    for b in recent_breaks:
        if b["direction"] == direction:
            sig_type = b["type"]  # "CHoCH" or "BOS"
            signals.append({
                "type": sig_type,
                "direction": direction,
                "level": b["level"],
                "timestamp": b["timestamp"],
                "weight": SIGNAL_WEIGHTS.get(sig_type, 1),
            })

    # 2. Displacement in trade direction
    displacements = detect_displacements(df, atr_period=14, atr_mult=thresholds["atr_mult"])
    recent_disps = [d for d in displacements if d["candle_index"] >= len(df) - lookback_bars]

    for d in recent_disps:
        if d["direction"] == direction:
            signals.append({
                "type": "displacement",
                "direction": direction,
                "body_atr_ratio": d["body_atr_ratio"],
                "timestamp": d["timestamp"],
                "weight": SIGNAL_WEIGHTS["displacement"],
            })

    # 3. Rejection wick from the zone
    for i in range(max(0, len(df) - lookback_bars), len(df)):
        row = df.iloc[i]
        candle_low = row["low"]
        candle_high = row["high"]
        candle_open = row["open"]
        candle_close = row["close"]
        body = abs(candle_close - candle_open)
        full_range = candle_high - candle_low

        if full_range == 0:
            continue

        if direction == "bullish" and candle_low <= zone_high:
            lower_wick = min(candle_open, candle_close) - candle_low
            if lower_wick / full_range >= 0.6 and candle_close > candle_open:
                ts = str(row["timestamp"]) if "timestamp" in df.columns else str(i)
                signals.append({
                    "type": "rejection_wick",
                    "direction": "bullish",
                    "wick_ratio": round(lower_wick / full_range, 2),
                    "timestamp": ts,
                    "weight": SIGNAL_WEIGHTS["rejection_wick"],
                })

        elif direction == "bearish" and candle_high >= zone_low:
            upper_wick = candle_high - max(candle_open, candle_close)
            if upper_wick / full_range >= 0.6 and candle_close < candle_open:
                ts = str(row["timestamp"]) if "timestamp" in df.columns else str(i)
                signals.append({
                    "type": "rejection_wick",
                    "direction": "bearish",
                    "wick_ratio": round(upper_wick / full_range, 2),
                    "timestamp": ts,
                    "weight": SIGNAL_WEIGHTS["rejection_wick"],
                })

    # 4. New FVG forming near the zone
    fvgs = detect_fvgs(df)
    recent_fvgs = [f for f in fvgs if f["candle_index"] >= len(df) - lookback_bars]

    for f in recent_fvgs:
        if f["type"] == direction:
            fvg_mid = f["midpoint"]
            zone_buffer = (zone_high - zone_low) * 0.5
            if (zone_low - zone_buffer) <= fvg_mid <= (zone_high + zone_buffer):
                signals.append({
                    "type": "fvg_formation",
                    "direction": direction,
                    "fvg_range": f"{f['bottom']:.2f}-{f['top']:.2f}",
                    "timestamp": f["timestamp"],
                    "weight": SIGNAL_WEIGHTS["fvg_formation"],
                })

    # Calculate weighted score
    total_score = sum(s.get("weight", 1) for s in signals)
    strong_signals = [s for s in signals if s.get("weight", 0) >= 2]
    confirmed = total_score >= min_score

    # Determine entry price
    current_price = float(df["close"].iloc[-1])
    entry_price = None
    if confirmed:
        if direction == "bullish":
            entry_price = min(current_price, (zone_low + zone_high) / 2)
        else:
            entry_price = max(current_price, (zone_low + zone_high) / 2)

    return {
        "confirmed": confirmed,
        "signals": signals,
        "signal_count": len(signals),
        "strong_signal_count": len(strong_signals),
        "weighted_score": total_score,
        "required_score": min_score,
        "zone_timeframe": zone_timeframe,
        "suggested_entry": round(entry_price, 2) if entry_price else None,
        "current_price": current_price,
        "zone": f"{zone_low:.2f}-{zone_high:.2f}",
        "reason": _summarize(signals, confirmed, total_score, min_score),
    }


def get_confirmation_timeframe(zone_timeframe: str) -> dict:
    """Return the appropriate confirmation timeframe parameters for a zone.

    Zone TF → what data to fetch for confirmation:
      4H → fetch 1H candles (look for 1H CHoCH/displacement)
      1H → fetch 15M candles
      15M → use existing 15M or fetch 5M
    """
    mapping = {
        "4h": {"interval": "1h", "range": "5d", "label": "1H"},
        "1h": {"interval": "15m", "range": "2d", "label": "15M"},
        "15m": {"interval": "15m", "range": "1d", "label": "15M"},
    }
    return mapping.get(zone_timeframe, mapping["1h"])


def _summarize(signals: list[dict], confirmed: bool, score: int, required: int) -> str:
    if not signals:
        return f"No confirmation signals. Score 0/{required}."
    types = [s["type"] for s in signals]
    status = "CONFIRMED" if confirmed else "WAITING"
    return f"{status} (score {score}/{required}): {', '.join(types)}"
