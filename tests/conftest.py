"""Shared test fixtures for ICT Paper Trading Simulator tests."""

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def sample_ohlcv():
    """Generate a synthetic OHLCV DataFrame with known swing points.

    Creates ~200 bars of 15-minute data with deliberate swing highs/lows,
    FVGs, and displacement candles baked in for deterministic testing.
    """
    np.random.seed(42)
    n = 200
    timestamps = pd.date_range("2025-04-07 00:00", periods=n, freq="15min", tz="UTC")

    # Build a price series with clear swings:
    # Up from 5000 to 5100 (bars 0-30), down to 5020 (30-60),
    # up to 5150 (60-100), down to 5050 (100-130), up to 5200 (130-170),
    # sideways 5180-5200 (170-200)
    close = np.zeros(n)
    close[0] = 5000
    trends = [
        (0, 30, 3.3),      # up
        (30, 60, -2.7),    # down
        (60, 100, 3.25),   # up
        (100, 130, -3.3),  # down
        (130, 170, 3.75),  # up
        (170, 200, 0.0),   # sideways
    ]
    for start, end, drift in trends:
        for i in range(start, min(end, n)):
            noise = np.random.randn() * 1.5
            close[i] = close[max(i - 1, 0)] + drift + noise

    # Derive OHLC from close
    high = close + np.abs(np.random.randn(n) * 3) + 2
    low = close - np.abs(np.random.randn(n) * 3) - 2
    open_ = np.roll(close, 1)
    open_[0] = close[0] - 1
    volume = np.random.randint(100, 5000, n)

    df = pd.DataFrame({
        "timestamp": timestamps,
        "open": np.round(open_, 2),
        "high": np.round(high, 2),
        "low": np.round(low, 2),
        "close": np.round(close, 2),
        "volume": volume,
    })
    return df


@pytest.fixture
def large_ohlcv():
    """Generate a larger synthetic OHLCV DataFrame (1000 bars) for stress testing."""
    np.random.seed(123)
    n = 1000
    timestamps = pd.date_range("2025-04-07 00:00", periods=n, freq="15min", tz="UTC")

    close = np.zeros(n)
    close[0] = 5000
    for i in range(1, n):
        # Random walk with mean reversion
        drift = -0.01 * (close[i - 1] - 5100)
        close[i] = close[i - 1] + drift + np.random.randn() * 5

    high = close + np.abs(np.random.randn(n) * 4) + 2
    low = close - np.abs(np.random.randn(n) * 4) - 2
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    volume = np.random.randint(100, 5000, n)

    df = pd.DataFrame({
        "timestamp": timestamps,
        "open": np.round(open_, 2),
        "high": np.round(high, 2),
        "low": np.round(low, 2),
        "close": np.round(close, 2),
        "volume": volume,
    })
    return df


@pytest.fixture
def ohlc_for_smc(sample_ohlcv):
    """Prepare sample OHLCV for the SMC library (DatetimeIndex, no timestamp col)."""
    df = sample_ohlcv.copy()
    df = df.set_index("timestamp")
    df.index.name = None
    return df


@pytest.fixture
def large_ohlc_for_smc(large_ohlcv):
    """Prepare large OHLCV for the SMC library."""
    df = large_ohlcv.copy()
    df = df.set_index("timestamp")
    df.index.name = None
    return df
