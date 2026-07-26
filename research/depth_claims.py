"""Retracement depth: is the OTE band special, or does depth just mean room?

ICT says the 61.8-79% retracement of a displacement-qualified swing is the
highest-probability entry, with 70.5% the sweet spot — a *zone*, not a trend. So
the claim predicts a **peak** in that band. A monotone rise with depth would say
something quite different and much duller: that price which has retraced further
simply has more room left to run in the leg's direction, which would explain why
traders believe in the zone without the zone being real.

The measurement rule, learned from three look-ahead defects in this programme
that all flattered the hypothesis:

    Measure from the bar a depth is **first reached**, never from where the
    retracement ended up.

Binning by "where it turned" conditions on the future — a retracement is only
known to have stopped at 70% after it stops. Taking the first bar that reaches
each band means one retracement can contribute to several bands, which is right:
when price touched 62% nobody knew whether it would halt or run to 85%.

The leg must also be **confirmed** before anything is measured. Swings from the
patched detector carry a `swing_length` lag, so a leg is not knowable at its
swing point. Measuring from the swing point is the exact bug fixed twice in
experiment 44.
"""
BANDS = [
    ("<38.2", 0.0, 0.382),
    ("38.2-61.8", 0.382, 0.618),
    ("61.8-79 OTE", 0.618, 0.79),
    ("79-100", 0.79, 1.0),
    (">100 invalid", 1.0, float("inf")),
]


def retracement_depth(price: float, leg_start: float, leg_end: float) -> float:
    """How far price has retraced back along a leg, as a fraction of its range.

    0.0 at the leg's extreme, 1.0 back at its origin, above 1.0 once the leg is
    invalidated. Direction-agnostic: works for a low-to-high leg and its mirror.
    """
    span = leg_end - leg_start
    if span == 0:
        return float("nan")
    return (leg_end - price) / span


def band_for(depth: float) -> str | None:
    """The band a depth falls in. Boundaries belong to the deeper band."""
    if depth != depth or depth < 0:          # NaN or not yet retracing
        return None
    for name, lo, hi in BANDS:
        if lo <= depth < hi:
            return name
    return None


def first_touch_by_band(high, low, leg_start: float, leg_end: float,
                        from_idx: int, limit: int, n: int) -> dict:
    """First bar index at which each band is reached, scanning forward.

    Args:
        from_idx: the leg's **confirmation** bar. Scanning starts after it,
            because the leg is not knowable before then.
        limit: how many bars the retracement is allowed.

    Returns {band_name: bar_index} for bands actually reached.
    """
    bullish = leg_end > leg_start
    out = {}
    for k in range(from_idx + 1, min(from_idx + 1 + limit, n)):
        # The retracement moves against the leg, so the relevant extreme of each
        # bar is the one furthest back along it.
        extreme = low[k] if bullish else high[k]
        depth = retracement_depth(extreme, leg_start, leg_end)
        b = band_for(depth)
        if b is not None and b not in out:
            out[b] = k
        if depth > 1.0:
            break                            # leg invalidated, stop tracking
    return out
