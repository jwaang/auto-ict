"""Joining a context timeframe to an execution timeframe without look-ahead.

The whole risk in a two-frame design sits here. A 15-minute bar stamped 10:15 is
only *complete* at 10:15, so any execution bar used to react to it must be
strictly after that instant. Selecting an execution bar at or before the context
bar's close reads the future — it lets the strategy respond to a 15-minute close
using a 1-minute bar that printed before that close existed.

Bar-close labelling makes this checkable: `resample_ohlcv` stamps every bar at
its close, so "strictly after" is a plain timestamp comparison and needs no
offset arithmetic.
"""
import numpy as np
import pandas as pd


def first_execution_bar_after(exec_stamps, context_close) -> int | None:
    """Index of the first execution bar strictly after a context bar's close.

    Args:
        exec_stamps: sorted DatetimeIndex or array of execution-frame timestamps.
        context_close: the context bar's close timestamp.

    Returns:
        Index into `exec_stamps`, or None when the context bar is at or past the
        end of the execution data.
    """
    idx = np.searchsorted(np.asarray(exec_stamps, dtype="datetime64[ns]"),
                          np.datetime64(pd.Timestamp(context_close).tz_localize(None)
                                        if pd.Timestamp(context_close).tzinfo
                                        else pd.Timestamp(context_close)),
                          side="right")
    return int(idx) if idx < len(exec_stamps) else None


def window_bounds(exec_stamps, context_close, minutes: int) -> tuple:
    """Half-open execution range (start, end) covering `minutes` after a close.

    Start is the first bar strictly after the context close; end is exclusive.
    Returns (None, None) when the context bar has no execution data after it.
    """
    start = first_execution_bar_after(exec_stamps, context_close)
    if start is None:
        return None, None
    deadline = pd.Timestamp(context_close) + pd.Timedelta(minutes=minutes)
    arr = np.asarray(exec_stamps, dtype="datetime64[ns]")
    naive = pd.Timestamp(deadline)
    if naive.tzinfo:
        naive = naive.tz_localize(None)
    end = int(np.searchsorted(arr, np.datetime64(naive), side="right"))
    return start, max(end, start)
