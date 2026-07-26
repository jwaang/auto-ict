"""Silver Bullet window arithmetic, and why the timeframe is forced.

The source gives three one-hour windows in New York time and requires the whole
sequence — market structure shift, then the fair value gap, then the retrace into
it — to complete inside one of them.

That constraint decides the execution timeframe rather than being a preference.
`backtest/strategies/common.py` records the measurement: a one-hour window holds
4 bars at 15-minute and 12 at 5-minute, while a structure shift alone needs a
swing to form, confirm and break — roughly 15 bars at `swing_length` 5. Confining
the chain to the window at those timeframes produced **zero trades over a full
year**, which is arithmetic rather than evidence about the strategy.

A one-hour window holds **60 one-minute bars**, so 1-minute is the only execution
timeframe on which the sequence can physically fit. That is presumably why the
source specifies 1m/3m/5m and never 15m.
"""
import pandas as pd

from config import SILVER_BULLET_WINDOWS

ET = "America/New_York"


def window_for(ts) -> str | None:
    """Which Silver Bullet window a timestamp falls in, if any.

    Windows are half-open on the hour: 10:00 is inside, 11:00 is not.
    """
    local = pd.Timestamp(ts).tz_convert(ET)
    for name, (start, end) in SILVER_BULLET_WINDOWS.items():
        if start <= local.hour < end:
            return name
    return None


def window_bounds(day, name: str) -> tuple:
    """(start, end) timestamps in UTC for one window on one ET calendar day."""
    start_h, end_h = SILVER_BULLET_WINDOWS[name]
    base = pd.Timestamp(day).tz_localize(ET)
    return (base + pd.Timedelta(hours=start_h)).tz_convert("UTC"), \
           (base + pd.Timedelta(hours=end_h)).tz_convert("UTC")


def bars_per_window(timeframe_minutes: int) -> int:
    """How many bars of a given timeframe fit in a one-hour window.

    The number that decides whether the sequence is possible at all: a structure
    shift needs roughly 15 bars, so anything returning fewer than that cannot
    produce a setup no matter what the market does.
    """
    return 60 // timeframe_minutes


def sequence_can_fit(timeframe_minutes: int, bars_needed: int = 15) -> bool:
    """Whether a full sequence can arithmetically complete inside the window."""
    return bars_per_window(timeframe_minutes) >= bars_needed
