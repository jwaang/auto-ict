# ICT Primitives — what each one claims, and how to test it

Written after testing several primitives against claims they do not make. Read
this before designing any primitive experiment.

## The one mistake to avoid

**Almost no ICT primitive is a directional signal that fires on formation.**

The first primitive test in this repo asked "after a bullish FVG forms, does
price rise?" That is not an ICT claim, so measuring it flat said nothing about
the methodology. The same error is available on every zone concept here.

## The unifying model: PD arrays

Order blocks, fair value gaps, breakers, inversion FVGs and mitigation blocks are
all **PD arrays** — price zones created by an event, which price then leaves and
is expected to *return to* and react from. The life cycle is always:

1. **Creation** — displacement, a gap, or a failed sweep marks the zone.
2. **Departure** — price moves away, leaving the zone unmitigated.
3. **Return** — price retraces back into the zone. *This is the entry trigger.*
4. **Reaction** — price is expected to resume the original direction from there.

So the claim is **conditional on the return**, and the correct test is always:

> Conditional on price returning to the zone, does it then move in the zone's
> implied direction more than it would from a matched control zone that price
> also returned to?

The control must be a zone price *also revisited*, at similar width and
distance. Comparing against zones price never reached measures "does price come
back", not "does this zone work".

OTE is not a zone. It is a **filter on how deep the retracement should be**
before the reaction is expected.

Liquidity pools are not zones either. They are **targets** and **sweep sites**.

## Primitive by primitive

### Fair Value Gap (FVG)

Three-candle imbalance: candle 3's low above candle 1's high (bullish, "BISI"),
or candle 3's high below candle 1's low (bearish, "SIBI").

**Claim, in two parts.** Price retraces *into* the gap to rebalance, **and then
continues in the gap's direction.** Both halves matter and they are separate
tests. The guide is explicit: "price is expected to retrace INTO this gap (fill
it) *before continuing up*".

**Status — the two halves separate.** Part one **holds**: real gaps fill 89.99%
within 48 bars against 85.69% for a geometry-matched control, paired difference
**+4.30 points, z +15.05**, n=43,536. Part two **fails**: conditional on price
returning to the gap (n=40,413), continuation in the gap's direction runs
47-49%, below a coin flip at every horizon and −0.5 to −1.1 points *below* a
matched control zone price also returned to.

**The FVG is a magnet, not a springboard.** Price comes back to the imbalance and
keeps going. An entry model waiting for the retracement and then trading the
continuation is relying on the half that does not work to pay for the half that
does.

**Not a claim:** that price rises after a bullish FVG forms. Measured flat, and
irrelevant.

### Consequent Encroachment (CE)

The 50% midpoint of an FVG.

**Claim.** Within the gap, CE is the *highest-probability reaction point* — price
often reaches CE and turns there rather than traversing the whole gap.

**Correct test.** Conditional on price entering an FVG, compare the reaction rate
at CE against other depths inside the same gap. Depth within the zone is the
variable, so the control is the rest of the gap, not a different gap.

### Order Block (OB)

The last down-close candle before a bullish displacement (or the last up-close
candle before a bearish one). The zone is the candle's full high-low range; its
midpoint is the **mean threshold**.

**Claim.** Price retraces to the OB and reacts in the displacement direction.

**Validity conditions** — an opposing candle alone is not an OB. It needs
displacement out of it, an FVG created by that displacement, a structure break,
and to be still unmitigated.

**Stated priority, strongest to weakest** — this ranking is itself testable:

1. OB causing a CHoCH *and* preceded by a liquidity sweep
2. OB causing a BOS after a pullback
3. OB inside the OTE zone
4. OB overlapping an unfilled FVG
5. Standalone OB

**Measurement warning.** `smc.ob()` is window-dependent. A full-frame pass over a
year finds 36 order blocks where non-overlapping 200-bar windows find 243, and
the survivors are mainly *unmitigated* ones — blocks price never traded back
into, which is selection on the future. That artifact produced a 97% win rate.
**Order blocks must be measured on a rolling window.**

### Breaker Block

A failed swing: price sweeps liquidity beyond a swing point, reverses hard,
breaks structure. The candles at the violated swing become the breaker, with
**flipped polarity** — a swept swing low becomes a bullish breaker.

**Claim.** Stronger than a plain OB, because trapped traders' stops sit there and
their orders were absorbed during the sweep. A sweep is *definitional*, not
optional.

**Correct test.** Reaction rate on return, against a plain OB retest. The claim is
comparative, so a plain OB is the right control.

### Inversion FVG (IFVG)

An FVG that price traded fully through. Its role flips: a filled bullish FVG
becomes resistance.

**Claim.** After full mitigation, the zone acts as support/resistance from the
opposite side.

**Correct test.** Conditional on a *return after full mitigation*, does price
react in the flipped direction more than at a matched control?

### Optimal Trade Entry (OTE)

The 61.8%–79% retracement of a swing; 70.5% is the stated sweet spot.

**Claim.** A retracement that ends in this band gives a better entry than a
shallower or deeper one. Valid only after displacement.

**Correct test.** Among retracements that reverse, is continuation quality better
for those terminating in 61.8–79% than for other depths? Depth is the variable,
so the control is other depths — not a different instrument or time.

### Displacement

An impulsive move, body greater than about 2× ATR, which creates the FVG and
validates the OB.

**Claim.** It is a *qualifier*, not a signal. It certifies that an OB or FVG is
worth trading.

**Correct test.** Does conditioning any zone test on displacement improve it? It
should never be tested standalone.

### Market Structure Shift (CHoCH) and Break of Structure (BOS)

CHoCH breaks structure *against* the prevailing trend (reversal); BOS breaks it
*with* the trend (continuation).

**Claim.** The **trigger** in the setup sequence — it confirms a new direction
after a sweep. ICT's claim is about the *ordering*: sweep, then MSS, then entry.

**Correct test.** Continuation after an MSS *that follows a sweep*, against an MSS
with no preceding sweep. Testing MSS alone misses the claim.

### Liquidity: pools and sweeps

Buy-side liquidity sits above highs, sell-side below lows. Pools form at equal
highs/lows, previous day high/low, session extremes.

**Sweep claim.** Price wicks beyond the level and closes back through it —
"the single most important pre-condition for an ICT entry. Without a sweep, the
setup is incomplete." Expected to be followed by displacement in the *opposite*
direction.

**Status — refuted, with the opposite significant.** Over 12,413 sweeps on
5-minute ES, the reversal rate is 44.72% at one bar, meaning **continuation
55.28%**, z **−11.68**, decaying to nothing by 24 bars, with both time halves
agreeing. Sweeps predict continuation, not reversal.

**Pool claim.** Liquidity pools are *targets*. Untested.

### Premium / Discount

Above or below the 50% of a dealing range. Sell in premium, buy in discount.

**Claim.** It says *where inside a bias* to act. It is **not** a direction vote.
Used as one it votes bearish ~97% of the time in a rising market, which is a
standing short bias. Already excluded from the bias vote for this reason.

### Power of Three / Judas Swing

Accumulation, manipulation, distribution within a session. The Judas swing is the
false move that engineers liquidity before the real one.

**Claim.** A session-shape claim, not a bar-level one. Test per session day.

## The constraint every result runs into

Measured on 5-minute ES over 2021-2024:

| | points |
|---|---|
| median FVG gap width | **0.75** |
| median distance price → gap midpoint | 1.88 |
| **round-turn cost** (spread + slippage + commission) | **1.02** |

**59.8% of fair value gaps are narrower than one round turn.**

Two primitives are confirmed real at z > 10 and both are worth less than the cost
of trading them: sweep continuation ~0.15 points of expectancy, FVG magnet ~0.08,
against 1.02 of cost.

This is a statement about **scale**, not about ICT. Five-minute ES structures are
1–3 points; a retail round turn is 1.02. Any signal defined on that geometry is
sub-spread by construction, whatever its name and however significant.

**So a primitive can be simultaneously real and untradeable, and most here are.**
Report significance and expectancy separately, and never let a large z imply a
tradeable edge.

## Testing rules learned the hard way

1. **Test the claim the concept makes**, not the one that is easy to measure.
2. **Condition on the return** for every PD array. Formation is not the trigger.
3. **Match the control to the claim** — same width, same distance, same side of
   price. A control mirrored to the opposite side confounds the test with trend
   and flipped one result's sign.
4. **Use a day-block bootstrap.** Detections cluster inside a session and
   overlapping forward windows share bars, so an independence assumption inflates
   every z.
5. **Pair the statistic when the design is paired.** Comparing two separate
   confidence intervals is cruder than a paired difference.
6. **Check window dependence** before trusting a full-frame detector count.
7. **Any edge above +5 points is a bug until the cause is found.** This caught the
   97% order-block artifact.
8. **`P(edge > 0)` across null seeds is not significance.** It measures
   null-estimation noise. Use sampling error.
