"""Candle helpers: ATR, body size, range, direction."""

import numpy as np
import pandas as pd


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate Average True Range."""
    high_low = df["high"] - df["low"]
    high_close = np.abs(df["high"] - df["close"].shift(1))
    low_close = np.abs(df["low"] - df["close"].shift(1))
    true_range = np.maximum(high_low, np.maximum(high_close, low_close))
    return true_range.rolling(window=period).mean()


def candle_body(df: pd.DataFrame) -> pd.Series:
    """Absolute candle body size."""
    return np.abs(df["close"] - df["open"])


def candle_range(df: pd.DataFrame) -> pd.Series:
    """Candle high-low range."""
    return df["high"] - df["low"]


def is_bullish(row) -> bool:
    """Check if candle is bullish (close >= open)."""
    return row["close"] >= row["open"]


def is_bearish(row) -> bool:
    """Check if candle is bearish (close < open)."""
    return row["close"] < row["open"]
