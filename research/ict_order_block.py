"""Order blocks to the specification, which requires four conditions not one.

`smc.ob()` is "the last opposing candle before displacement" and implements none
of what the source states. A bullish order block needs all four:

  1. the next candle **grabs the prior candle's low** — a liquidity sweep
  2. it **closes above the prior candle's high** — complete engulfment
  3. an **FVG prints** inside or above the zone
  4. an **MSS confirms** upward

Bearish mirrors all four. The zone is the opposing candle's full high-low range
and its midpoint is the *mean threshold*.

This matters beyond the order block itself: it is the foundation of the breaker,
the mitigation block, the Unicorn and the Silver Bullet entry leg, so a loose
definition has been propagating into four unmeasured concepts.

Each condition is a separate predicate so each can be unit-tested and so the
funnel can report which one rejects most candidates — the interesting number when
a detector finds far fewer setups than expected.
"""
import numpy as np


def grabs_prior_extreme(high, low, i, bullish: bool) -> bool:
    """Condition 1 — the impulse candle takes out the opposing candle's extreme."""
    return low[i + 1] < low[i] if bullish else high[i + 1] > high[i]


def engulfs(high, low, close, i, bullish: bool) -> bool:
    """Condition 2 — and closes beyond its far side, a complete engulfment."""
    return close[i + 1] > high[i] if bullish else close[i + 1] < low[i]


def is_opposing_candle(open_, close, i, bullish: bool) -> bool:
    """A bullish OB is built on a down-close candle, and vice versa."""
    return close[i] < open_[i] if bullish else close[i] > open_[i]


def has_fvg(fvg_idx: dict, i: int, bullish: bool, within: int = 3) -> bool:
    """Condition 3 — the displacement leaves an imbalance of the same polarity."""
    want = "bullish" if bullish else "bearish"
    return any(fvg_idx.get(k, {}).get("type") == want
               for k in range(i + 1, i + 1 + within))


def mss_confirm_index(mss_by_idx: dict, i: int, bullish: bool,
                      within: int = 10) -> int | None:
    """Condition 4 — the bar at which structure confirms, or None.

    The *index* matters, not just the fact. A block is not identifiable until its
    confirming shift prints, so anything reacting to the block must start after
    this bar. Returning a bool here is what let an earlier version count retests
    that happened before confirmation existed, inflating the measured reaction by
    8 to 18 points.
    """
    want = "bullish" if bullish else "bearish"
    for k in range(i + 1, i + 1 + within):
        if mss_by_idx.get(k) == want:
            return k
    return None


def detect_order_blocks(bars, fvgs: list, mss_list: list,
                        fvg_within: int = 3, mss_within: int = 10) -> tuple:
    """Order blocks meeting all four conditions, plus a rejection funnel.

    Returns (blocks, funnel). Each block carries the zone, its mean threshold and
    the index of the impulse candle, and nothing derived from the future — no
    `mitigated` flag, because that is what turned a full-frame pass into a 97%
    win-rate artifact.
    """
    open_ = bars["open"].to_numpy()
    high = bars["high"].to_numpy()
    low = bars["low"].to_numpy()
    close = bars["close"].to_numpy()
    n = len(close)

    fvg_idx = {f["candle_index"]: f for f in fvgs}
    mss_by_idx = {m["index"]: m["direction"] for m in mss_list}

    blocks = []
    funnel = {"not_opposing": 0, "no_grab": 0, "no_engulf": 0, "no_fvg": 0,
              "no_mss": 0, "accepted": 0}

    for i in range(n - 1):
        for bullish in (True, False):
            if not is_opposing_candle(open_, close, i, bullish):
                funnel["not_opposing"] += 1
                continue
            if not grabs_prior_extreme(high, low, i, bullish):
                funnel["no_grab"] += 1
                continue
            if not engulfs(high, low, close, i, bullish):
                funnel["no_engulf"] += 1
                continue
            if not has_fvg(fvg_idx, i, bullish, fvg_within):
                funnel["no_fvg"] += 1
                continue
            confirm = mss_confirm_index(mss_by_idx, i, bullish, mss_within)
            if confirm is None:
                funnel["no_mss"] += 1
                continue
            funnel["accepted"] += 1
            blocks.append({
                "type": "bullish" if bullish else "bearish",
                "high": float(high[i]),
                "low": float(low[i]),
                "mean_threshold": float((high[i] + low[i]) / 2),
                "candle_index": i,
                "impulse_index": i + 1,
                # The block only exists once structure confirms it. Nothing may
                # react to it before this bar.
                "confirmed_index": confirm,
            })

    return blocks, funnel
