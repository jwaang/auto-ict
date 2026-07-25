"""Market-regime classification and per-regime result attribution.

The previous version of this module hardcoded four one-week presets chosen by
their realised return ("+2.94% return", "-2.83% return"). Two things were wrong
with that, and both are worth remembering:

- **It contaminated the holdout.** Three of the four weeks fell inside
  2026-01-01..2026-07-23, so running them during iteration would have spent the
  holdout without anyone noticing.
- **The windows were chosen by looking at the answer.** Picking a test period by
  what price did in it is hindsight selection over the data the strategy is then
  judged on.

This version fixes both. A month's regime label is computed from the **prior**
month only, so it is knowable at the window's open and a live system could act on
it. And nothing here selects windows — the whole span is run once and results are
*attributed* per regime afterwards.

Attribution beats splicing for three reasons: a single month yields ~30 trades at
15m which is far too few to read, splicing fragments the equity curve so drawdown
and streaks stop meaning anything across slices, and it discards the regime
transitions where drawdowns actually happen.

Honest caveat on the labels: prior-month volatility predicts next-month volatility
reasonably well, but prior-month trend efficiency is a weak predictor of next-month
efficiency. Measured on the 2021-08..2024-12 training span, the vol dimension
separates realised behaviour (choppy_highvol std 5.55% vs trending_lowvol 3.26%)
while the trend dimension barely does. Treat the trend half of each label as a
guess about conditions, not a description of them.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

REGIMES = ("trending_lowvol", "trending_highvol", "choppy_lowvol", "choppy_highvol")


def monthly_features(df_1m: pd.DataFrame) -> pd.DataFrame:
    """Per-month trend efficiency and annualised volatility.

    Efficiency is net move divided by total path length: near 1 means price went
    somewhere in a straight line, near 0 means it churned.
    """
    from data.historical import resample_ohlcv

    daily = resample_ohlcv(df_1m, "1D", session_aligned=True).set_index("timestamp")
    daily["ret"] = daily["close"].pct_change()

    # Both legs must measure the same ground. Taking `net` from the first daily
    # OPEN while `path` starts at the first daily CLOSE lets net cover a day that
    # path does not, and efficiency then exceeds 1 — measured at 1.05 on a
    # monotone series, which is meaningless. Close-to-close on both.
    monthly = daily.resample("MS").agg(first=("close", "first"), last=("close", "last"))
    path = daily["close"].diff().abs().resample("MS").sum()
    monthly["efficiency"] = ((monthly["last"] - monthly["first"]).abs() / path).clip(upper=1.0)
    monthly["vol"] = daily["ret"].resample("MS").std() * np.sqrt(252) * 100
    return monthly.dropna(subset=["efficiency", "vol"])


def classify_months(
    df_1m: pd.DataFrame,
    start: str | None = None,
    end: str | None = None,
) -> pd.Series:
    """Label each month by regime using only data available before it starts.

    Thresholds are the medians of the prior-month signals over the labelled span,
    which is why `start`/`end` should be the training span and never the holdout —
    otherwise the thresholds themselves would carry holdout information.

    Returns:
        Series indexed by "YYYY-MM" string, holding a regime label.
    """
    features = monthly_features(df_1m)
    if start:
        features = features[features.index >= start]
    if end:
        features = features[features.index < end]

    # Shift by one month: a label must be knowable at the window's open.
    features["prior_eff"] = features["efficiency"].shift(1)
    features["prior_vol"] = features["vol"].shift(1)
    features = features.dropna(subset=["prior_eff", "prior_vol"])
    if features.empty:
        return pd.Series(dtype=object)

    eff_median = features["prior_eff"].median()
    vol_median = features["prior_vol"].median()

    labels = {}
    for stamp, row in features.iterrows():
        trend = "trending" if row["prior_eff"] >= eff_median else "choppy"
        vol = "highvol" if row["prior_vol"] >= vol_median else "lowvol"
        labels[stamp.strftime("%Y-%m")] = f"{trend}_{vol}"
    return pd.Series(labels, name="regime")


def attribute(monthly_returns: dict, classification: pd.Series) -> dict:
    """Split a run's monthly P&L across regimes.

    Takes `calc_stats()["monthly_returns"]`, so this works on results already in
    the experiment store — no extra backtests needed to get regime coverage.
    """
    out: dict[str, dict] = {}
    for month, pnl in (monthly_returns or {}).items():
        regime = classification.get(month)
        if regime is None:
            continue
        bucket = out.setdefault(regime, {"months": 0, "net_pnl": 0.0, "winning_months": 0})
        bucket["months"] += 1
        bucket["net_pnl"] = round(bucket["net_pnl"] + pnl, 2)
        bucket["winning_months"] += 1 if pnl > 0 else 0
    for bucket in out.values():
        bucket["pnl_per_month"] = round(bucket["net_pnl"] / bucket["months"], 2)
    return out


def robustness(attribution: dict) -> dict:
    """How evenly a result is spread across regimes.

    A config that only earns in one regime is a regime bet, not an edge, and it is
    the shape overfitting takes when a sweep is scored on a single aggregate. The
    worst regime matters more than the average one for anything heading to
    production.
    """
    if not attribution:
        return {}
    per_month = {k: v["pnl_per_month"] for k, v in attribution.items()}
    return {
        "regimes_covered": len(per_month),
        "regimes_profitable": sum(1 for v in per_month.values() if v > 0),
        "worst_regime": min(per_month, key=per_month.get),
        "worst_regime_pnl_per_month": min(per_month.values()),
        "best_regime": max(per_month, key=per_month.get),
        "best_regime_pnl_per_month": max(per_month.values()),
    }
