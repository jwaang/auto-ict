"""Classify a fair value gap by strength: weak, quietly strong, or exceptional.

Not every imbalance is tradeable, and the source is specific about which to
discard. From innercircletrader.net:

  weak            forms entirely inside the previous large candle's range; the
                  displacement failed to break prior structure. "Often blows
                  right through it on retest." These are traps — drop them.
  quietly strong  candle 2 breaks the previous candle's range, but candle 3
                  does not continue beyond candle 2's extreme. Displacement was
                  real, follow-through hesitant. Trade only with external
                  confluence.
  exceptional     candle 2 breaks the previous range AND candle 3 extends
                  beyond candle 2's extreme. Institutional commitment. "When
                  price returns to an exceptional FVG, the reaction is almost
                  always violent and immediate."

Experiments 36 and 37 pooled all 43,536 gaps, which mixes the tier the source
says to discard with the tier it says to trade, so a difference between them
would be averaged away. This is the variable that pooling hid.

Indexing note, verified empirically rather than assumed: `candle_index` on an
FVG record from `smc_adapter.detect_fvgs` points at the **third** candle, since
the patched detector emits the signal once candle 3 closes. So candle 1 is
`idx - 2`, the displacement candle is `idx - 1`, and the candle before the
pattern is `idx - 3`.
"""

WEAK = "weak"
QUIETLY_STRONG = "quietly_strong"
EXCEPTIONAL = "exceptional"


def classify_fvg(fvg: dict, high, low, displacement_idx: set | None = None) -> str | None:
    """Strength tier for one FVG, or None if there is no room to judge it.

    Args:
        fvg: record from `smc_adapter.detect_fvgs`, needing `candle_index` and
            `type`.
        high, low: arrays of the same frame the FVG was detected on.
        displacement_idx: optional set of bar indices carrying a detected
            displacement. Supply it and "exceptional" additionally requires the
            middle candle to *be* a displacement.

            Without it, a geometry-only reading calls 72% of gaps exceptional on
            5-minute ES, which cannot be what a category meant to denote
            institutional commitment describes — "candle 3 makes a new extreme"
            is a low bar in a trending market. The source also asks for a
            substantial body and minimal wicks on the middle candle, and that is
            what this restores.
    """
    idx = fvg.get("candle_index")
    if idx is None or idx < 3 or idx >= len(high):
        return None

    prior, c2, c3 = idx - 3, idx - 1, idx
    bullish = fvg.get("type") == "bullish"

    # Did the displacement candle break out of the preceding candle's range?
    # If not, the imbalance formed inside prior structure and is a trap.
    if bullish:
        broke_prior = high[c2] > high[prior]
        continued = high[c3] > high[c2]
    else:
        broke_prior = low[c2] < low[prior]
        continued = low[c3] < low[c2]

    if not broke_prior:
        return WEAK
    if not continued:
        return QUIETLY_STRONG
    if displacement_idx is not None and c2 not in displacement_idx:
        return QUIETLY_STRONG
    return EXCEPTIONAL


def classify_all(fvgs: list, high, low, displacement_idx: set | None = None) -> dict:
    """Tier every FVG, returning {tier: [fvg, ...]} plus the unjudgeable count."""
    out = {WEAK: [], QUIETLY_STRONG: [], EXCEPTIONAL: [], "skipped": []}
    for f in fvgs:
        tier = classify_fvg(f, high, low, displacement_idx)
        out["skipped" if tier is None else tier].append(f)
    return out
