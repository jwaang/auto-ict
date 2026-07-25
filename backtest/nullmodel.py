"""An empirical null: random entries at the strategy's own geometry.

Every cell so far has been scored against `stop / (stop + target)`, the
first-passage probability that a driftless walk reaches its target before its
stop. That formula assumes **unlimited time**. Real trades are force-closed at
16:00 ET, and because the target sits farther away than the stop it takes longer
to reach, so the cutoff removes target-hits more often than stop-hits. Scoring a
time-censored sample against an uncensored null therefore understates every
result — the mirror image of counting session-end closes as wins.

Rather than patch the formula with another approximation, measure the null. Draw
random entry times and random directions on the same bars, give them stop and
target distances drawn from what the strategy actually used, and resolve them
through the same 1-minute first-touch logic and the same 16:00 cutoff. The only
difference left between null and strategy is *which moment and which direction
was chosen* — which is precisely the thing under test.

This also captures what no formula does: real ES drift, volatility clustering,
overnight gaps and the intraday shape of the session.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.intrabar import Intrabar

_SESSION_TZ = "America/New_York"
_SESSION_END_HOUR = 16  # matches engine._SESSION_END_HOUR


def session_end(entry_ts: pd.Timestamp) -> pd.Timestamp:
    """The 16:00 ET cutoff that applies to a trade entered at `entry_ts`.

    The engine closes a position on the first bar whose ET hour is 16, and with
    bar-close labelling that bar is stamped 16:00 ET. An entry at or after the
    cutoff belongs to the next session.
    """
    local = entry_ts.tz_convert(_SESSION_TZ)
    cutoff = local.normalize() + pd.Timedelta(hours=_SESSION_END_HOUR)
    if local >= cutoff:
        cutoff += pd.Timedelta(days=1)
    return cutoff.tz_convert("UTC")


def run_null_model(
    minute_df: pd.DataFrame,
    entry_times: pd.DatetimeIndex,
    stop_points: np.ndarray,
    target_multiples: np.ndarray,
    n: int = 5000,
    seed: int = 0,
    paired: bool = False,
    intrabar: Intrabar | None = None,
    closes: pd.Series | None = None,
) -> dict:
    """Resolve `n` random entries and report how often the target came first.

    Args:
        minute_df: 1-minute OHLC frame with a `timestamp` column.
        entry_times: Bars an entry may be taken on, in the entry timeframe.
        stop_points: Stop distances observed in a real run; sampled with
            replacement so the null's geometry matches the strategy's.
        target_multiples: Target distances as a multiple of the stop, likewise
            sampled from the real run.
        n: Number of random entries.
        seed: Fixed so a null is reproducible and cannot be re-rolled.
        paired: When True the three arrays are index-aligned — one real trade per
            position — and a draw takes a trade's own bar, stop and target and
            randomises only the **direction**.

            The unpaired form samples entry times across every bar, which tests
            entry timing and direction together. But it leaves a confound: if a
            strategy's entries cluster at a particular hour they get a particular
            amount of time before the 16:00 cutoff, while a uniform null gets the
            session average. Different censoring means the two are not comparable.
            The paired form removes that entirely — same bar, same geometry — so
            what it measures is whether the bias rule knows which way to go.
            Run both and the result decomposes into timing skill and direction
            skill.

    Returns:
        Barrier count and win rate for the random entries, the number censored
        by the cutoff, and the analytic benchmark for comparison.
    """
    if len(entry_times) == 0 or len(stop_points) == 0:
        return {}
    if paired and not (len(entry_times) == len(stop_points) == len(target_multiples)):
        raise ValueError("paired mode needs entry_times, stop_points and "
                         "target_multiples index-aligned")

    rng = np.random.default_rng(seed)
    # Both are read-only views over the same span. A caller running several nulls
    # — one per setup type, say — should build them once and pass them in rather
    # than copying the minute frame per call.
    if intrabar is None:
        intrabar = Intrabar(minute_df)
    if closes is None:
        closes = minute_df.set_index("timestamp")["close"]

    if paired:
        picks = rng.integers(0, len(entry_times), size=n)
        eligible = entry_times
        stops = np.asarray(stop_points)[picks]
        mults = np.asarray(target_multiples)[picks]
    else:
        # Entries in the final session have no room to resolve before the cutoff.
        eligible = entry_times[entry_times < entry_times[-1].normalize()]
        if len(eligible) == 0:
            eligible = entry_times
        picks = rng.integers(0, len(eligible), size=n)
        stops = rng.choice(stop_points, size=n, replace=True)
        mults = rng.choice(target_multiples, size=n, replace=True)
    dirs = np.where(rng.random(n) < 0.5, "LONG", "SHORT")

    tp = sl = censored = missing = 0
    for k in range(n):
        entry_ts = eligible[picks[k]]
        # The entry fills at the close of the signal bar, as the engine does.
        idx = closes.index.searchsorted(entry_ts, side="right") - 1
        if idx < 0:
            missing += 1
            continue
        entry = float(closes.iloc[idx])
        stop_pts, mult = float(stops[k]), float(mults[k])
        if dirs[k] == "LONG":
            stop, target = entry - stop_pts, entry + stop_pts * mult
        else:
            stop, target = entry + stop_pts, entry - stop_pts * mult

        outcome = intrabar.first_touch(entry_ts, session_end(entry_ts),
                                       str(dirs[k]), stop, target)
        if outcome == "TP_HIT":
            tp += 1
        elif outcome == "SL_HIT":
            sl += 1
        else:
            censored += 1

    barrier_n = tp + sl
    analytic = float(np.mean(1.0 / (1.0 + mults))) * 100
    return {
        "null_n": n,
        "null_barrier_n": barrier_n,
        "null_win_rate": round(tp / barrier_n * 100, 2) if barrier_n else None,
        "null_censored_n": censored,
        "null_censored_pct": round(censored / n * 100, 1),
        "null_missing_n": missing,
        "analytic_win_rate": round(analytic, 2),
        "median_stop_pts": round(float(np.median(stops)), 2),
        "median_target_mult": round(float(np.median(mults)), 2),
    }


def paired_geometry_from_trades(
    trades: list[dict],
) -> tuple[pd.DatetimeIndex, np.ndarray, np.ndarray]:
    """Entry bar, stop distance and target multiple for each real trade.

    Index-aligned for `run_null_model(..., paired=True)`, so a draw reuses a
    trade's own moment and geometry and randomises only its direction.
    """
    times, stops, mults = [], [], []
    for t in trades:
        if t.get("status") != "CLOSED" or not t.get("entry_time"):
            continue
        risk = abs(t["entry_price"] - t["stop_loss"])
        reward = abs(t["take_profit"] - t["entry_price"])
        if risk > 0 and reward > 0:
            times.append(pd.Timestamp(t["entry_time"]))
            stops.append(risk)
            mults.append(reward / risk)
    if not times:
        return pd.DatetimeIndex([]), np.asarray([]), np.asarray([])
    idx = pd.DatetimeIndex(times)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    return idx, np.asarray(stops), np.asarray(mults)


def geometry_from_trades(trades: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Stop distances and target multiples a real run used, for sampling.

    Only barrier and forced exits carry usable geometry; anything with a zero
    stop is discarded rather than clamped.
    """
    stops, mults = [], []
    for t in trades:
        if t.get("status") != "CLOSED":
            continue
        risk = abs(t["entry_price"] - t["stop_loss"])
        reward = abs(t["take_profit"] - t["entry_price"])
        if risk > 0 and reward > 0:
            stops.append(risk)
            mults.append(reward / risk)
    return np.asarray(stops), np.asarray(mults)
