"""Per-run parameter overrides for backtest experiments.

Most constants in `config.py` are pulled into the importing module's namespace
with `from config import X`, which binds the value at import time. Rebinding
`config.X` later therefore has no effect on the module that already imported it,
so a sweep cannot vary those constants by touching config.

This module holds one mutable dict that consumers read at *call* time instead.
It generalises the pattern already proven by
`ict.smc_adapter.set_swing_length_override`, which the engine sets and clears
around each run.

Fork-safe: `ProcessPoolExecutor` workers get their own copy of module globals,
so one cell's overrides cannot leak into another's.

Usage in a consumer:

    from backtest import params
    min_rr = params.get("min_rr_ratio", MIN_RR_RATIO)

Usage in a runner:

    with params.overrides({"min_rr_ratio": 1.5}):
        run_backtest(...)
"""

from __future__ import annotations

from contextlib import contextmanager

_overrides: dict = {}


def set_overrides(values: dict | None) -> None:
    """Replace the whole override set. Pass None or {} to clear."""
    global _overrides
    _overrides = dict(values) if values else {}


def get(name: str, default):
    """Read an override, falling back to the caller's config default."""
    return _overrides.get(name, default)


def active() -> dict:
    """Current overrides, for recording alongside a result."""
    return dict(_overrides)


@contextmanager
def overrides(values: dict | None):
    """Apply overrides for the duration of a block, then restore."""
    previous = _overrides
    set_overrides(values)
    try:
        yield
    finally:
        set_overrides(previous)
