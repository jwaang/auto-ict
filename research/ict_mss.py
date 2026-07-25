"""Market Structure Shift, to the specification rather than to the library.

The source is precise and the repo's detector is not:

  * A swing is broken **by a body close past the extreme** — "a wick poke is not
    an MSS."
  * The breaking candle must be a **displacement** — large real body, minimal
    wicks, ideally leaving a fair value gap.
  * `CHoCH` is the same break *without* displacement — "CHoCH asks the reversal
    question; MSS answers it." `BOS` breaks with the trend, not against it.

`smc_adapter.detect_bos_choch` requires neither the close nor the displacement,
so everything measured through it has been CHoCH at best. This module is the
version the specification describes, kept in research until it has earned a place
in `ict/`.

The swing series comes from the patched detector, so swings are confirmed with a
lag of `swing_length` bars and carry no look-ahead: a swing is only known once
its confirmation bar has printed, and only bars after that can break it.
"""
import numpy as np


def detect_mss(bars, swings, displacement_idx, confirm_lag: int = 5) -> list[dict]:
    """Body-close breaks of a confirmed swing, on a displacement candle.

    Args:
        bars: frame with `high`, `low`, `close` columns.
        swings: list of {type, level, candle_index} from
            `smc_adapter.detect_swings`. `candle_index` is the *confirmation*
            bar, which is when the swing becomes known.
        displacement_idx: set of bar indices carrying a displacement, from
            `ict/displacement.py::detect_displacements`.
        confirm_lag: bars to wait after the confirmation index before a break
            counts, guarding against a swing and its break on the same bar.

    Returns:
        List of {index, direction, level, swing_index}, one per break, in bar
        order. A given swing produces at most one MSS — the first break of it.
    """
    close = bars["close"].to_numpy()
    n = len(close)

    highs = sorted((s for s in swings if s["type"] == "swing_high"),
                   key=lambda s: s["candle_index"])
    lows = sorted((s for s in swings if s["type"] == "swing_low"),
                  key=lambda s: s["candle_index"])

    out = []
    for pool, direction in ((highs, "bullish"), (lows, "bearish")):
        for s in pool:
            start = s["candle_index"] + confirm_lag
            level = s["level"]
            if start >= n:
                continue
            # First bar whose *close* clears the level, not whose wick does.
            body = close[start:] > level if direction == "bullish" else close[start:] < level
            hit = np.flatnonzero(body)
            if len(hit) == 0:
                continue
            i = start + int(hit[0])
            if i not in displacement_idx:
                # A break without displacement is a CHoCH, not an MSS.
                continue
            out.append({"index": i, "direction": direction, "level": float(level),
                        "swing_index": int(s["candle_index"])})

    out.sort(key=lambda r: r["index"])
    return out


def first_mss_after(mss_list: list[dict], after_idx: int, direction: str,
                    within: int) -> dict | None:
    """The first MSS of `direction` in (after_idx, after_idx + within].

    Used to confirm a liquidity sweep: the source wants the structure shift to
    follow the sweep, in the direction the setup expects, and reasonably soon.
    """
    for m in mss_list:
        if m["index"] <= after_idx:
            continue
        if m["index"] > after_idx + within:
            return None
        if m["direction"] == direction:
            return m
    return None
