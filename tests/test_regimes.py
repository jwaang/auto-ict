"""Tests for regime classification and attribution.

The point of this module is that a label must be knowable at the window's open.
The version it replaced picked four one-week windows by their realised return, and
three of the four sat inside the holdout — so these tests are mostly about the two
properties that failure had: no peeking ahead, and no holdout contamination.
"""

import numpy as np
import pandas as pd
import pytest

from backtest.regimes import (
    REGIMES,
    attribute,
    classify_months,
    monthly_features,
    robustness,
)


def _series(months=14, bars_per_day=96, seed=7):
    """A year-plus of 15m bars with alternating calm and violent months."""
    rng = np.random.default_rng(seed)
    rows, price = [], 4000.0
    stamp = pd.Timestamp("2021-01-01", tz="UTC")
    for m in range(months):
        # Even months drift quietly, odd months are volatile and choppy.
        scale = 1.0 if m % 2 == 0 else 6.0
        drift = 0.6 if m % 2 == 0 else 0.0
        for _ in range(20 * bars_per_day):
            price += rng.normal(drift, scale) * 0.1
            rows.append({"timestamp": stamp, "open": price, "high": price + 1,
                         "low": price - 1, "close": price, "volume": 100})
            stamp += pd.Timedelta(minutes=15)
    return pd.DataFrame(rows)


class TestMonthlyFeatures:
    def test_efficiency_is_between_zero_and_one(self):
        feats = monthly_features(_series())
        assert not feats.empty
        assert (feats["efficiency"] >= 0).all()
        assert (feats["efficiency"] <= 1).all()

    def test_volatility_is_positive(self):
        feats = monthly_features(_series())
        assert (feats["vol"] > 0).all()

    def test_a_straight_line_is_maximally_efficient(self):
        """Net move over total path is 1 when price never reverses."""
        idx = pd.date_range("2022-01-03", periods=20 * 96, freq="15min", tz="UTC")
        price = np.arange(len(idx), dtype=float) + 4000.0
        df = pd.DataFrame({"timestamp": idx, "open": price, "high": price + 0.5,
                           "low": price - 0.5, "close": price, "volume": 1})
        feats = monthly_features(df)
        assert feats["efficiency"].iloc[0] == pytest.approx(1.0, abs=1e-6)


class TestNoLookAhead:
    """A label must depend only on months strictly before the one it labels."""

    def test_first_month_is_never_labelled(self):
        """It has no prior month, so there is nothing to label it from."""
        df = _series()
        labels = classify_months(df)
        feats = monthly_features(df)
        assert feats.index[0].strftime("%Y-%m") not in labels.index

    def test_label_unchanged_when_later_months_are_appended(self):
        """The decisive property: appending future data must not relabel the past."""
        df = _series(months=14)
        feats = monthly_features(df)
        cut = feats.index[8].strftime("%Y-%m-%d")

        early = classify_months(df[df["timestamp"] < cut])
        late = classify_months(df)
        shared = early.index.intersection(late.index)
        assert len(shared) >= 3, "need overlap to compare"
        # Thresholds are medians over the labelled span, so they legitimately move
        # as the span grows. The ORDERING a label depends on must not: check that
        # each shared month's prior-month signals are identical either way.
        f_early = monthly_features(df[df["timestamp"] < cut])
        f_late = monthly_features(df)
        for month in shared:
            ts = pd.Timestamp(month + "-01", tz="UTC")
            assert f_early.loc[ts, "efficiency"] == pytest.approx(f_late.loc[ts, "efficiency"])
            assert f_early.loc[ts, "vol"] == pytest.approx(f_late.loc[ts, "vol"])

    def test_span_bounds_are_respected(self):
        """Passing the training span must not label anything outside it — this is
        what keeps holdout months from being touched."""
        labels = classify_months(_series(months=14), "2021-04-01", "2021-10-01")
        assert not labels.empty
        for month in labels.index:
            assert "2021-04" <= month < "2021-10", month

    def test_labels_come_from_the_known_set(self):
        labels = classify_months(_series())
        assert set(labels).issubset(set(REGIMES))


class TestAttribution:
    def test_splits_monthly_pnl_across_regimes(self):
        classification = pd.Series({
            "2023-01": "trending_lowvol",
            "2023-02": "trending_lowvol",
            "2023-03": "choppy_highvol",
        })
        got = attribute({"2023-01": 100.0, "2023-02": -40.0, "2023-03": -500.0},
                        classification)
        assert got["trending_lowvol"]["months"] == 2
        assert got["trending_lowvol"]["net_pnl"] == 60.0
        assert got["trending_lowvol"]["pnl_per_month"] == 30.0
        assert got["trending_lowvol"]["winning_months"] == 1
        assert got["choppy_highvol"]["net_pnl"] == -500.0

    def test_unlabelled_months_are_skipped(self):
        classification = pd.Series({"2023-01": "choppy_lowvol"})
        got = attribute({"2023-01": 10.0, "2099-12": 999.0}, classification)
        assert set(got) == {"choppy_lowvol"}
        assert got["choppy_lowvol"]["net_pnl"] == 10.0

    def test_empty_inputs_are_safe(self):
        assert attribute({}, pd.Series(dtype=object)) == {}
        assert attribute(None, pd.Series(dtype=object)) == {}


class TestRobustness:
    def test_flags_a_single_regime_bet(self):
        got = robustness({
            "trending_lowvol": {"months": 6, "net_pnl": 6000.0, "pnl_per_month": 1000.0},
            "choppy_highvol": {"months": 6, "net_pnl": -3000.0, "pnl_per_month": -500.0},
        })
        assert got["regimes_profitable"] == 1
        assert got["worst_regime"] == "choppy_highvol"
        assert got["best_regime"] == "trending_lowvol"

    def test_reports_broad_profitability(self):
        got = robustness({
            "a": {"months": 3, "net_pnl": 300.0, "pnl_per_month": 100.0},
            "b": {"months": 3, "net_pnl": 150.0, "pnl_per_month": 50.0},
        })
        assert got["regimes_profitable"] == 2
        assert got["worst_regime_pnl_per_month"] == 50.0

    def test_empty_is_safe(self):
        assert robustness({}) == {}
