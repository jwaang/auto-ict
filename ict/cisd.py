"""Change In State of Delivery (CISD).

ICT's current favourite entry trigger, and one of only two concepts that are
**causally clean** by construction — the other being the fair value gap. That
matters here because order blocks, breakers and the Unicorn model are all defined
retroactively ("the last down candle before the up move" reads future data), so a
mechanised backtest of them is suspect no matter how carefully it is written.

The rule, in ICT's terms: delivery has changed state when a candle **body closes**
through the **opening price of the opposing candle series**. Wicks do not count — a
poke through is not a CISD.

Concretely, for a bullish CISD:

1. Find a run of consecutive down candles: sellers were delivering price.
2. The reference is the **open of the first candle in that run** — where the
   sellers began.
3. The signal fires on the first later candle whose **close** exceeds that
   reference. Delivery has flipped from bearish to bullish.
4. The stop sits beyond the run's low, which is the level that invalidates it.

Bearish is the mirror. Everything uses closed candles and a price known before the
signal bar opened, so no value can be revised by later data.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def detect_cisd(df: pd.DataFrame, max_run_age: int = 30) -> list[dict]:
    """Find CISD events.

    Args:
        df: OHLC frame, oldest first.
        max_run_age: How many bars a run stays eligible. Without a bound, a run
            from hundreds of bars ago could fire on an unrelated move — the same
            staleness problem the FVG+OB overlap finder had.

    Returns:
        List of dicts, oldest first, each with:
            type            "bullish" or "bearish"
            reference       the opposing series' opening price
            candle_index    bar the signal fired on
            run_start/end   bounds of the opposing candle run
            run_extreme     the run's low (bullish) or high (bearish); stop level
            timestamp       signal bar timestamp
    """
    if len(df) < 3:
        return []

    open_ = df["open"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    index = df["timestamp"] if "timestamp" in df.columns else df.index

    down = close < open_
    up = close > open_
    n = len(df)
    events: list[dict] = []

    for bullish in (True, False):
        series = down if bullish else up
        run_start = None
        # A run stays armed until it fires or ages out. Only the most recent
        # unfired run is tracked, which is what "the opposing series" means.
        armed: dict | None = None

        for i in range(n):
            if series[i]:
                if run_start is None:
                    run_start = i
                continue

            if run_start is not None:
                # Run just ended at i-1. Arm it, replacing any older one.
                armed = {
                    "run_start": run_start,
                    "run_end": i - 1,
                    "reference": open_[run_start],
                    "run_extreme": (low[run_start:i].min() if bullish
                                    else high[run_start:i].max()),
                }
                run_start = None

            if armed is None:
                continue
            if i - armed["run_end"] > max_run_age:
                armed = None
                continue

            broke = close[i] > armed["reference"] if bullish else close[i] < armed["reference"]
            if broke:
                events.append({
                    "type": "bullish" if bullish else "bearish",
                    "reference": round(float(armed["reference"]), 4),
                    "candle_index": i,
                    "run_start": armed["run_start"],
                    "run_end": armed["run_end"],
                    "run_extreme": round(float(armed["run_extreme"]), 4),
                    "timestamp": str(index.iloc[i] if hasattr(index, "iloc") else index[i]),
                })
                armed = None

    events.sort(key=lambda e: e["candle_index"])
    return events


def latest_cisd(events: list[dict], direction: str, current_index: int,
                max_age: int = 10) -> dict | None:
    """Most recent CISD matching a trade direction, if it is still fresh.

    `direction` is "LONG" or "SHORT". A CISD from twenty bars ago is history, not
    a trigger, so `max_age` bounds how long one stays actionable.
    """
    wanted = "bullish" if direction == "LONG" else "bearish"
    for event in reversed(events):
        if event["type"] != wanted:
            continue
        age = current_index - event["candle_index"]
        if age < 0:
            continue
        return event if age <= max_age else None
    return None
