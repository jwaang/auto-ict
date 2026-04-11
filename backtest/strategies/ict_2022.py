"""ICT 2022 Model strategy — Sweep -> MSS -> FVG Entry.

From docs/ICT_Trading_Strategies_Combined_Research.md:
  Sweep a key liquidity zone (PDH/PDL, equal highs/lows), then retrace
  into an FVG after MSS for entry, with stops beyond the sweep and
  targets to the opposite liquidity side. Minimum 1:3 R:R.

Kill zone windows: London (3-5 AM ET), New York (7-11 AM ET).
"""

from __future__ import annotations

import pandas as pd
from zoneinfo import ZoneInfo

from backtest.strategies.common import (
    build_decision,
    calc_atr_simple,
    calc_stop_loss,
    check_entry_criteria,
    detect_sweep_mss_fvg_sequence,
    find_take_profit,
    get_entry_price,
    get_htf_bias,
    run_smc_detections,
)

_ET = ZoneInfo("America/New_York")

# ICT 2022 Model kill zones (ET hours)
_KILL_ZONES = {
    "london": (3, 5),
    "new_york": (7, 11),
}

_MIN_RR = 3.0
_DEFAULT_TP_RR = 3.0


class ICT2022Strategy:
    name = "ict_2022"

    def evaluate(
        self,
        windowed: dict[str, pd.DataFrame],
        ticker: str,
        current_time: pd.Timestamp,
        htf_cache: dict,
    ) -> dict | None:
        """Evaluate the ICT 2022 Model setup at this bar."""

        # --- Kill zone gate (check early to skip work) ---
        et_time = current_time.astimezone(_ET)
        in_kz = False
        for start_h, end_h in _KILL_ZONES.values():
            if start_h <= et_time.hour < end_h:
                in_kz = True
                break
        if not in_kz:
            return None

        # --- Run SMC detections (cached for HTF) ---
        bias_det = run_smc_detections(windowed["bias"], "bias", htf_cache)
        swing_det = run_smc_detections(windowed["swing"], "swing", htf_cache)
        entry_det = run_smc_detections(windowed["entry"], "entry", htf_cache)

        if not bias_det or not entry_det:
            return None

        # --- HTF bias ---
        htf_bias = get_htf_bias(bias_det, swing_det, entry_det)
        if htf_bias == "neutral":
            return None

        direction = htf_bias
        current_price = entry_det["current_price"]
        entry_df = windowed["entry"]
        current_idx = len(entry_df) - 1

        # Lookback scales with timeframe — 1min needs more bars for same time span
        if len(entry_df) >= 2:
            bar_gap = (entry_df["timestamp"].iloc[-1] - entry_df["timestamp"].iloc[-2]).total_seconds() / 60
        else:
            bar_gap = 15
        lookback = max(100, int(240 / max(bar_gap, 1)))

        # --- Detect sweep -> MSS -> FVG sequence on entry TF ---
        sequence = detect_sweep_mss_fvg_sequence(
            entry_det, direction, current_idx, lookback=lookback,
        )
        if sequence is None:
            return None

        # --- Entry criteria checklist ---
        passed, reason = check_entry_criteria(
            htf_bias, direction, sequence, entry_det,
            current_price, current_time, ticker, in_kill_zone=in_kz,
        )
        if not passed:
            return None

        # --- Entry price (must be in FVG/OB zone now) ---
        entry_price, entry_type = get_entry_price(sequence, direction, current_price)
        if entry_price is None:
            return None

        # --- Stop loss ---
        atr = calc_atr_simple(entry_df)
        stop_loss = calc_stop_loss(direction, sequence["sweep"], atr, ticker)

        # --- Take profit ---
        take_profit = find_take_profit(
            direction, entry_price, stop_loss, entry_det, default_rr=_DEFAULT_TP_RR,
        )

        # --- R:R check ---
        risk = abs(entry_price - stop_loss)
        if risk == 0:
            return None
        reward = abs(take_profit - entry_price)
        rr = reward / risk
        if rr < _MIN_RR:
            return None

        # --- Build decision ---
        retracement = entry_det.get("retracement", {})
        return build_decision(
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            htf_bias=htf_bias,
            setup_type="ICT_2022_Model",
            entry_type=entry_type,
            sequence=sequence,
            in_ote=retracement.get("in_ote", False),
        )
