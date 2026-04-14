"""Regime-based backtest week presets.

Defines representative weeks for each market regime so backtests can
validate across diverse conditions quickly (~12 min for 4 weeks vs
~75 min for a full 6-month run).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RegimeWeek:
    """A representative week for a specific market regime."""
    label: str        # e.g. "strong_uptrend"
    start: str        # Monday date "YYYY-MM-DD"
    end: str          # Friday date "YYYY-MM-DD"
    description: str  # Human-readable summary


# ES regime weeks selected from IBKR 6-month data (Oct 2025 - Apr 2026)
# Chosen to maximize diversity: uptrend, downtrend, choppy, low-vol
ES_REGIME_WEEKS = [
    RegimeWeek(
        "strong_uptrend",
        "2025-11-24", "2025-11-28",
        "Nov 30 week: +2.94% return, strong directional move up",
    ),
    RegimeWeek(
        "strong_downtrend",
        "2026-03-02", "2026-03-06",
        "Mar 8 week: -2.83% return, sharp selloff",
    ),
    RegimeWeek(
        "choppy",
        "2026-01-20", "2026-01-24",
        "Jan 25 week: |return| < 0.5%, range > 1.5%, reversal traps",
    ),
    RegimeWeek(
        "low_volatility",
        "2025-10-27", "2025-10-31",
        "Nov 2 week: 1.22% range, low activity, tests setup filtering",
    ),
]


def get_regime_weeks(preset: str = "ES") -> list[RegimeWeek]:
    """Get regime week presets for a given asset.

    Args:
        preset: Asset preset name (currently only "ES" supported)

    Returns:
        List of RegimeWeek definitions
    """
    presets = {
        "ES": ES_REGIME_WEEKS,
    }
    if preset.upper() not in presets:
        raise ValueError(f"Unknown regime preset: {preset!r}. Available: {list(presets.keys())}")
    return presets[preset.upper()]
