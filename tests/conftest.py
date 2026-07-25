"""Shared test fixtures for ICT Paper Trading Simulator tests."""

from pathlib import Path

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
def known_swings_ohlcv():
    """50 bars with 4 clear, deterministic swings for manual verification.

    Pattern: up→peak(bar15)→down→trough(bar30)→up→peak(bar42)→down
    Uses large moves with zero noise so swings are unambiguous.
    """
    n = 50
    timestamps = pd.date_range("2025-06-01 00:00", periods=n, freq="15min", tz="UTC")
    close = np.array([
        # Bars 0-15: climb from 100 to 115 (peak at bar 15)
        100, 101, 102, 103, 104, 105, 106, 107, 108, 109,
        110, 111, 112, 113, 114, 115,
        # Bars 16-30: drop from 114 to 90 (trough at bar 30)
        114, 112, 110, 108, 106, 104, 102, 100, 98, 96,
        94, 93, 92, 91, 90,
        # Bars 31-42: climb from 92 to 120 (peak at bar 42)
        92, 95, 98, 101, 104, 107, 110, 113, 115, 117,
        119, 120,
        # Bars 43-49: drop from 118 to 105
        118, 116, 113, 110, 108, 106, 105,
    ], dtype=float)
    high = close + 1.0
    low = close - 1.0
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    volume = np.full(n, 1000)
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": open_, "high": high, "low": low, "close": close, "volume": volume,
    })


@pytest.fixture
def known_fvg_ohlcv():
    """30 bars with deliberate bullish FVG at bars 10-12 and bearish FVG at bars 20-22.

    Bullish FVG: bar10 high < bar12 low (gap up).
    Bearish FVG: bar20 low > bar22 high (gap down).
    """
    n = 30
    timestamps = pd.date_range("2025-06-01 00:00", periods=n, freq="15min", tz="UTC")
    # Steady prices except at FVG locations
    close = np.full(n, 100.0)
    high = np.full(n, 101.0)
    low = np.full(n, 99.0)
    open_ = np.full(n, 100.0)

    # Bullish FVG at bars 10-12: bar10 high=101, bar11 big green candle, bar12 low=103
    # Gap: bar10.high(101) < bar12.low(103) → bullish FVG top=103, bottom=101
    close[10] = 100; high[10] = 101; low[10] = 99; open_[10] = 99.5
    close[11] = 104; high[11] = 105; low[11] = 100; open_[11] = 100  # big bullish
    close[12] = 105; high[12] = 106; low[12] = 103; open_[12] = 104

    # Bearish FVG at bars 20-22: bar20 low=99, bar21 big red candle, bar22 high=97
    # Gap: bar20.low(99) > bar22.high(97) → bearish FVG top=99, bottom=97
    close[20] = 100; high[20] = 101; low[20] = 99; open_[20] = 100.5
    close[21] = 96; high[21] = 100; low[21] = 95; open_[21] = 100   # big bearish
    close[22] = 95; high[22] = 97; low[22] = 94; open_[22] = 96

    # Fill remaining bars with gentle noise to avoid accidental FVGs
    for i in range(n):
        if i not in (10, 11, 12, 20, 21, 22):
            close[i] = 100 + (i % 3) * 0.1
            high[i] = close[i] + 0.5
            low[i] = close[i] - 0.5
            open_[i] = close[i] - 0.1

    volume = np.full(n, 1000)
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": open_, "high": high, "low": low, "close": close, "volume": volume,
    })


@pytest.fixture
def flat_ohlcv():
    """100 bars of perfectly flat price — should produce no detections."""
    n = 100
    timestamps = pd.date_range("2025-06-01 00:00", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": np.full(n, 100.0),
        "high": np.full(n, 100.5),
        "low": np.full(n, 99.5),
        "close": np.full(n, 100.0),
        "volume": np.full(n, 1000),
    })


@pytest.fixture
def tiny_ohlcv_3():
    """3 bars — absolute minimum for most detections."""
    timestamps = pd.date_range("2025-06-01", periods=3, freq="15min", tz="UTC")
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": [100.0, 101.0, 99.0],
        "high": [101.0, 102.0, 100.0],
        "low": [99.0, 100.0, 98.0],
        "close": [101.0, 99.0, 100.0],
        "volume": [1000, 1000, 1000],
    })


@pytest.fixture
def tiny_ohlcv_1():
    """1 bar — absolute minimum."""
    timestamps = pd.date_range("2025-06-01", periods=1, freq="15min", tz="UTC")
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": [100.0], "high": [101.0], "low": [99.0], "close": [100.5], "volume": [1000],
    })


def _to_smc(df):
    """Helper to convert OHLCV DataFrame to SMC-ready format."""
    out = df.copy()
    out = out.set_index("timestamp")
    out.index.name = None
    return out


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


# Real market data. `historical/` is gitignored, so these skip when it is absent.
REAL_DATA = Path("historical/ES-5y/glbx-mdp3-20210724-20260723.ohlcv-1m.dbn.zst")
_real_cache: dict = {}


def _real_15m(bars: int = 1500):
    """Load a slice of real front-month ES, resampled to 15m.

    A gapless random walk cannot exercise weekend gaps, the daily maintenance
    halt, holidays, contract rolls or DST, all of which real ES has. Causality
    invariants that only hold on synthetic data are not invariants.
    """
    if "df" not in _real_cache:
        from data.historical import load_continuous_contract, resample_ohlcv
        df = load_continuous_contract(str(REAL_DATA))
        _real_cache["df"] = resample_ohlcv(df, "15min")
    # Take from the middle of the span so a contract roll falls inside the slice.
    full = _real_cache["df"]
    start = len(full) // 2
    return full.iloc[start:start + bars].reset_index(drop=True)


@pytest.fixture
def real_ohlc_for_smc():
    """Real ES 15m bars in SMC form, or skip if the dataset is not present."""
    if not REAL_DATA.exists():
        pytest.skip(f"real dataset not present at {REAL_DATA}")
    return _to_smc(_real_15m())


@pytest.fixture(params=["synthetic", "real"])
def any_ohlc_for_smc(request, large_ohlcv):
    """Causality fixture parameterized over synthetic and real data."""
    if request.param == "real":
        if not REAL_DATA.exists():
            pytest.skip(f"real dataset not present at {REAL_DATA}")
        return _to_smc(_real_15m())
    return _to_smc(large_ohlcv)
