"""One-minute resolution for things the entry timeframe cannot answer.

Two questions need finer bars than the entry timeframe:

**Which barrier was hit first.** When a 15-minute bar's range spans both the stop
and the target, `PositionManager._check_position_fill` assumes the stop. That is the
conservative guess and it is deterministic, but it is still a guess — and on a
measured 2023 run there were 204 stops against 76 targets, so the guess is not a
rounding error. The 1-minute path settles it.

**How far a trade actually travelled.** Maximum favourable and adverse excursion in
R says whether a target was ever reachable. If favourable excursion rarely reaches
the target's R even on winners, the geometry is wrong by construction and no amount
of entry tuning fixes it.

Timestamps are bar-close labelled, so a 15m bar stamped 10:15 covers the 1m bars
stamped 10:01 through 10:15.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class Intrabar:
    """Read-only 1-minute view, indexed for range queries."""

    def __init__(self, df_1m: pd.DataFrame):
        # A DatetimeIndex, not a numpy array: converting tz-aware timestamps
        # through np.datetime64 silently drops the timezone and then refuses to
        # compare against tz-aware values.
        self._ts = pd.DatetimeIndex(df_1m["timestamp"])
        self._high = df_1m["high"].to_numpy()
        self._low = df_1m["low"].to_numpy()

    def _slice(self, start, end) -> tuple[int, int]:
        """Half-open index range for bars with start < timestamp <= end."""
        lo = int(self._ts.searchsorted(pd.Timestamp(start), side="right"))
        hi = int(self._ts.searchsorted(pd.Timestamp(end), side="right"))
        return lo, hi

    def extremes(self, start, end) -> tuple[float, float] | None:
        """Highest high and lowest low over (start, end]."""
        lo, hi = self._slice(start, end)
        if hi <= lo:
            return None
        return float(self._high[lo:hi].max()), float(self._low[lo:hi].min())

    def first_touch(
        self,
        start,
        end,
        direction: str,
        stop: float,
        target: float,
    ) -> str | None:
        """Say whether the stop or the target was reached first.

        Returns "SL_HIT", "TP_HIT", or None when neither is touched in the window.
        A single 1-minute bar containing both still cannot be split, so that case
        falls back to the stop — pessimistic, and rare enough not to matter.
        """
        lo, hi = self._slice(start, end)
        if hi <= lo:
            return None

        highs = self._high[lo:hi]
        lows = self._low[lo:hi]
        if direction == "LONG":
            stop_bars = np.flatnonzero(lows <= stop)
            target_bars = np.flatnonzero(highs >= target)
        else:
            stop_bars = np.flatnonzero(highs >= stop)
            target_bars = np.flatnonzero(lows <= target)

        first_stop = stop_bars[0] if stop_bars.size else None
        first_target = target_bars[0] if target_bars.size else None

        if first_stop is None and first_target is None:
            return None
        if first_target is None:
            return "SL_HIT"
        if first_stop is None:
            return "TP_HIT"
        # Same minute holds both — keep the pessimistic reading.
        return "TP_HIT" if first_target < first_stop else "SL_HIT"

    def excursion(self, pos_direction: str, entry: float, stop: float,
                  start, end) -> dict:
        """Favourable and adverse excursion in R over the life of a trade.

        R is the initial stop distance, so these are directly comparable across
        trades with different stop widths.
        """
        risk = abs(entry - stop)
        got = self.extremes(start, end)
        if not got or risk == 0:
            return {}
        high, low = got
        if pos_direction == "LONG":
            favourable, adverse = high - entry, entry - low
        else:
            favourable, adverse = entry - low, high - entry
        return {
            "mfe_r": round(favourable / risk, 2),
            "mae_r": round(adverse / risk, 2),
        }
