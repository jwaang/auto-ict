"""Strategy registry for backtesting.

Strategies encapsulate specific ICT setups with their own detection logic,
entry/exit rules, and R:R requirements. The engine dispatches to a strategy's
evaluate() method instead of the generic confluence scoring path.
"""

from __future__ import annotations

from typing import Protocol

import pandas as pd


class BacktestStrategy(Protocol):
    """Protocol that all backtest strategies must implement."""

    name: str

    def evaluate(
        self,
        windowed: dict[str, pd.DataFrame],
        ticker: str,
        current_time: pd.Timestamp,
        htf_cache: dict,
    ) -> dict | None:
        """Evaluate whether to take a trade at this bar.

        Args:
            windowed: Point-in-time {label: DataFrame} for each timeframe
            ticker: Ticker symbol
            current_time: Current bar timestamp
            htf_cache: Mutable dict for caching HTF detections across calls

        Returns:
            Decision dict compatible with validate_trade/positions.py, or None.
        """
        ...


def get_strategy(name: str) -> BacktestStrategy:
    """Factory: return a strategy instance by name."""
    if name == "ict_2022":
        from backtest.strategies.ict_2022 import ICT2022Strategy
        return ICT2022Strategy()
    elif name == "silver_bullet":
        from backtest.strategies.silver_bullet import SilverBulletStrategy
        return SilverBulletStrategy()
    else:
        raise ValueError(f"Unknown strategy: {name!r}. Choose from: ict_2022, silver_bullet")
