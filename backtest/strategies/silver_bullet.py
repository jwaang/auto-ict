"""Silver Bullet strategy — timing-filtered Sweep -> MSS -> FVG Entry.

From docs/ICT_Trading_Strategies_Combined_Research.md:
  Same sweep->displacement->FVG/OB entry structure, restricted to three
  narrow 1-hour windows. The sweep, MSS, and FVG must all form WITHIN
  the active window. Minimum 1:2 R:R.

Silver Bullet Windows (ET):
  - 3:00-4:00 AM  (London)
  - 10:00-11:00 AM (NY AM — highest probability)
  - 2:00-3:00 PM  (NY PM)
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

# Silver Bullet windows (ET hours)
_SB_WINDOWS = {
    "sb_london": (3, 4),
    "sb_ny_am": (10, 11),
    "sb_ny_pm": (14, 15),
}

_MIN_RR = 2.0
_DEFAULT_TP_RR = 2.0


def _get_window_bar_bounds(
    entry_df: pd.DataFrame,
    current_time: pd.Timestamp,
    window_start_hour: int,
    window_end_hour: int,
) -> tuple[int, int] | None:
    """Find bar index bounds for the current SB window in the entry DataFrame.

    Returns (start_idx, end_idx) or None if no bars fall in the window.
    """
    et_time = current_time.astimezone(_ET)
    # Build window start/end as timestamps on the same date
    window_start = et_time.replace(hour=window_start_hour, minute=0, second=0, microsecond=0)
    window_end = et_time.replace(hour=window_end_hour, minute=0, second=0, microsecond=0)

    # Convert to UTC for comparison with bar timestamps
    ws_utc = pd.Timestamp(window_start)
    we_utc = pd.Timestamp(window_end)

    timestamps = entry_df["timestamp"]
    mask = (timestamps >= ws_utc) & (timestamps <= we_utc)
    indices = mask[mask].index.tolist()

    if not indices:
        return None
    return (indices[0], indices[-1])


class SilverBulletStrategy:
    name = "silver_bullet"

    def evaluate(
        self,
        windowed: dict[str, pd.DataFrame],
        ticker: str,
        current_time: pd.Timestamp,
        htf_cache: dict,
    ) -> dict | None:
        """Evaluate the Silver Bullet setup at this bar."""

        # --- Silver Bullet window gate (check early) ---
        et_time = current_time.astimezone(_ET)
        active_window = None
        for name, (start_h, end_h) in _SB_WINDOWS.items():
            if start_h <= et_time.hour < end_h:
                active_window = (name, start_h, end_h)
                break
        if active_window is None:
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

        # --- Get window bar bounds for sequence scoping ---
        entry_df = windowed["entry"]
        current_idx = len(entry_df) - 1
        _, window_start_h, window_end_h = active_window

        window_bounds = _get_window_bar_bounds(
            entry_df, current_time, window_start_h, window_end_h,
        )
        if window_bounds is None:
            return None

        # Lookback scales with timeframe
        if len(entry_df) >= 2:
            bar_gap = (entry_df["timestamp"].iloc[-1] - entry_df["timestamp"].iloc[-2]).total_seconds() / 60
        else:
            bar_gap = 15
        lookback = max(100, int(240 / max(bar_gap, 1)))

        # --- Detect sweep -> MSS -> FVG within the SB window ---
        # Pass window_bounds so the entire causal chain (sweep, MSS, FVG)
        # is constrained to the active Silver Bullet hour.
        sequence = detect_sweep_mss_fvg_sequence(
            entry_det, direction, current_idx, lookback=lookback,
            window_bounds=window_bounds,
        )
        if sequence is None:
            return None

        # --- Entry criteria checklist (SB counts as kill zone) ---
        passed, reason = check_entry_criteria(
            htf_bias, direction, sequence, entry_det,
            current_price, current_time, ticker, in_kill_zone=True,
        )
        if not passed:
            return None

        # --- Entry price ---
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
            setup_type=f"Silver_Bullet_{active_window[0]}",
            entry_type=entry_type,
            sequence=sequence,
            in_ote=retracement.get("in_ote", False),
        )
