# ICT primitives — what each claims, how it is used, how to test it

**Read this before designing any primitive experiment.** It exists because
several experiments here measured claims ICT does not make, and one measured a
mistake the source explicitly names.

Sources: `docs/ICT_Trading_Strategies_Combined_Research.md`,
`docs/ICT-STRATEGY-GUIDE.md`, and the innercircletrader.net tutorials on the fair
value gap, valid FVGs, order blocks, breaker blocks, market structure shift,
liquidity sweep vs run, the Silver Bullet and the 2022 model.

## The two mistakes that cost the most

**1. No primitive is a directional signal that fires on formation.** The first
test here asked "after a bullish FVG forms, does price rise?" That is not a
claim, so measuring it flat said nothing. Every zone concept invites the same
error.

**2. A primitive alone is not a setup.** Each is a *filter* or a *location*. The
methodology's claim is about the **ordering** — bias, then liquidity, then
trigger, then entry location. Testing a component in isolation and finding
nothing is the expected result, not evidence about ICT.

## The unifying model: PD arrays

Order blocks, fair value gaps, breakers, inversion FVGs and mitigation blocks are
**PD arrays** — zones created by an event, which price leaves, **returns to**, and
is expected to react from. The return is the trigger, never the formation.

The correct test is always: *conditional on price returning to the zone, does it
move in the zone's direction more than from a matched control zone price also
returned to?* A control price never reached measures "does price come back", not
"does this zone work".

**OTE is not a zone** — it is a filter on retracement depth.
**Liquidity pools are not zones** — they are targets and sweep sites.

---

## Liquidity: sweep vs run

The most important distinction here, and the one whose omission produced a wrong
published conclusion.

| | mechanics | predicts |
|---|---|---|
| **Sweep** | wick through the level, **close back inside**, limited displacement, resolves in 1-3 candles | reversal |
| **Run** | **close beyond** the level, sustained displacement, no return to the prior range | continuation |

**The selector is higher-timeframe bias, not the candle:**

> "If the higher-timeframe direction agrees with the side that just got swept,
> expect a **run**; if it disagrees, expect a **sweep**."

Trade protocol: HTF bias → mark liquidity and the PD array → sweep with
close-back-inside → **LTF MSS confirms** → enter on the **PD array retest, not the
wick** → stop beyond the swept level with a buffer → target opposite-side
liquidity.

Named mistakes: entering on the wick ("not a trade"), stops too tight at the
swept level, trading against HTF bias, skipping LTF structure confirmation, and
mistaking the first grab for the real move — it is often **inducement** and
reverses before the second delivers direction.

**Status — confirmed, and the strongest result in this programme.** Sweep form
with bias *agreeing* continues: **+5.57 points, z 10.24, n=10,108** on 1-minute,
replicated at 5m (+3.75) and 15m (+5.00). The neutral-bias cell is flat
(z < 1.2) — where the methodology makes no prediction there is no effect. First
result to pass `|z| > 3`, `n >= 5000` and independent-timeframe replication.
Experiment 40.

**Superseded:** earlier readings of this as "sweeps predict continuation, ICT is
backwards" (z −11.68) were a **mixture artifact** — no bias condition, so runs
and sweeps were pooled with reversal predicted for both — compounded by a tie bug
that doubled the apparent size. Corrected, the pooled figure is −2.33.

**Pool claim.** Liquidity pools as *targets* — untested.

---

## Market Structure Shift (MSS)

A swing broken by a **displacement move in the opposite direction**.

- The break needs a **body close past the extreme — "a wick poke is not an MSS."**
- The breaking candle has a large real body, minimal wicks, ideally leaves an FVG.

| | breaks | displacement | meaning |
|---|---|---|---|
| **BOS** | with trend | — | continuation |
| **CHoCH** | counter-trend | no | "asks the reversal question" |
| **MSS** | counter-trend | **yes** | "answers it" |

**The sequence separating a valid MSS from a fake one:** liquidity sweep at the
extreme → failure to hold → MSS opposite. Without the prior sweep: "more
whipsaws and failed reversals — skip or reduce size."

Entry is the **retest of the PD array created during the displacement leg**, not
the displacement move. Stop beyond the wick of the swept extreme preceding the
MSS. Win rate "dramatically higher when the MSS prints inside a higher-timeframe
PD array tap."

**Repo gap:** `smc_adapter.detect_bos_choch` does not require a body close, and
CHoCH is treated as MSS in places. `ict/confluence.py::_detect_mss` does require
a causal displacement, which is closer to the specification.

---

## Fair Value Gap (FVG)

Three-candle imbalance: candle 3's low above candle 1's high (bullish, BISI), or
candle 3's high below candle 1's low (bearish, SIBI).

**Claim in two parts** — price retraces *into* the gap to rebalance, **and then
continues in the gap's direction.** Separate tests.

**Status — the halves separate.**
- Part one **holds**: real gaps fill 89.99% within 48 bars against 85.69% for a
  geometry-matched control; paired difference **+4.30, z +15.05**, n=43,536. The
  magnet strengthens with tier (+3.93 / +6.00 / +6.37).
- Part two **fails**: conditional on the return (n=40,413), continuation is
  −0.5 to −1.1 points *below* a matched control at every horizon.

**The FVG is a magnet, not a springboard.** Price returns to the imbalance and
keeps going. An entry model waiting for the retracement and trading the
continuation relies on the half that does not work to pay for the half that does.

On absolutes: an earlier version said continuation runs "47-49%, below a coin
flip". With ties excluded it is ~50.6% — *at* the coin flip. The paired
difference survives; the absolute claim was a tie artifact.

**The trigger is not zone contact.** The source lists "entering at the FVG touch
without confirmation" as a common mistake — the trigger is the **LTF MSS at the
zone**, after bias, premium/discount, displacement and a non-choppy regime.

### Strength tiers

| tier | rule | guidance |
|---|---|---|
| **weak** | displacement candle fails to break the prior candle's range | traps — discard |
| **quietly strong** | breaks it; candle 3 does not extend beyond | only with confluence |
| **exceptional** | breaks it, candle 3 extends beyond, **and candle 2 is a displacement** | primary entries |

Without the displacement requirement 72% of gaps land in "exceptional", which
cannot describe institutional commitment. With it: 9.2% / 87.5% / 3.2%.

**Status:** no tier reacts positively at adequate power (exceptional is −0.08 at
h=1, n=5,241). **Weak gaps are confirmed traps** — −1.81 at z −3.89, n=25,722. A
+3.22 seen at n=1,197 did not replicate. `research/fvg_quality.py`, experiments
38 and 39.

### The FVG family

First-presented FVG (session's first), inversion FVG, implied FVG, Balanced Price
Range (two opposite FVGs overlapping), breakaway gap (never filled), NWOG
(weekend), NDOG (17:00-18:00 NY), SIBI/BISI naming.

**Consequent Encroachment (CE)** — the 50% midpoint, the highest-probability
reaction point *within* the gap. Its control is the rest of the same gap. Weakly
positive (~+1 point) and untrusted: reaching the midpoint conditions on having
travelled further.

**IOFED** — entry at the gap's very edge, the earliest possible fill.

---

## Order Block

The last down-close candle before a bullish impulse (or up-close before bearish).
Zone is the candle's full range; its midpoint is the **mean threshold**.

**Four conditions, not one.** A bullish OB requires:

1. the next candle **grabs the prior candle's low** (a liquidity sweep)
2. it **closes above the prior candle's high** (complete engulfment)
3. an **FVG prints** on the lower timeframe inside or above the zone
4. an **LTF MSS** confirms upward

OBs without an FVG are "much weaker". Counter-bias OBs fail more often. OBs
**weaken with each successive retest** — the first is strongest. HTF order blocks
produce the biggest moves; LTF ones are for execution. Stop 10-20 pips beyond the
extreme; target the next draw on liquidity.

Stated priority, strongest first: OB causing a CHoCH *and* preceded by a sweep →
OB causing a BOS after a pullback → OB inside OTE → OB overlapping an unfilled
FVG → standalone OB.

Foundation of: breaker, mitigation block, Unicorn, the Silver Bullet entry leg,
SCOB.

**Repo gap — this matters.** `smc.ob()` is "last opposing candle before
displacement" with **no engulfment, no sweep, no FVG and no MSS requirement**.
Every order-block measurement here used the loose version.

**Measurement warning.** `smc.ob()` is window-dependent: a full-frame pass over a
year finds 36 where non-overlapping 200-bar windows find 243, and the survivors
are mainly *unmitigated* blocks — price never traded back into them, which is
selection on the future. That produced a 97% win-rate artifact. **Order blocks
must be measured on a rolling window.**

---

## Breaker Block

A **failed** order block.

1. an OB forms at a swing extreme against the prevailing HTF trend
2. price sweeps liquidity at the OB extreme
3. the OB is violated by a **body close**, not a wick
4. structure shifts opposite on the lower timeframe
5. the broken OB becomes the retest entry zone in the **new** direction

**Breaker vs OB:** "same level, opposite trade" — an OB is a continuation entry,
a breaker a reversal one. **Breaker vs mitigation block:** a mitigation block is
an older OB retested in its *original* direction; visually similar, opposite
implication.

Entry on the breaker retest, narrowed to the final candle of the original OB
sequence. Stop beyond the wick of the swept extreme. Target the next liquidity
pool. Breakers fail counter-bias. Its control is a **plain OB retest**, since the
claim is comparative.

---

## Inversion FVG (IFVG)

An FVG price traded fully through; its role flips, so a filled bullish FVG becomes
resistance. Test conditional on a *return after full mitigation*, against a
matched control.

---

## Optimal Trade Entry (OTE)

The 61.8%–79% retracement of a swing; 70.5% is the sweet spot. Valid only after
displacement. Past 79% weakens the setup; failing to reach 61.8% means do not
chase. **Control is other retracement depths**, since depth is the variable.

---

## Displacement

Impulsive move, body greater than about 2× ATR. A **qualifier**, never a signal —
it certifies an OB or FVG is worth trading, and creates the FVG. Never test
standalone.

---

## Premium / Discount

Above or below the 50% of a dealing range. Says **where inside a bias** to act —
it is *not* a direction vote. Used as one it votes bearish ~97% of the time in a
rising market, a standing short bias. Already excluded from the bias vote here.

---

## Power of Three / Judas Swing

Accumulation, manipulation, distribution within a session; the Judas swing is the
false move that engineers liquidity before the real one. A session-shape claim,
not a bar-level one — test per session day.

---

## Composed setups

### Silver Bullet
Windows **03:00-04:00, 10:00-11:00, 14:00-15:00 NY** (matches
`config.SILVER_BULLET_WINDOWS`). Mark liquidity on 15m before the window; execute
on 1-3m; MSS toward the next liquidity draw; displacement leaving an FVG;
validate the FVG's premium/discount side; wait for the retrace into the FVG;
enter at the tap; stop beyond the creating candle's wick; target the next
liquidity pool at roughly 1:3.

**"A liquidity raid alone is not a signal."** The whole sequence must complete
inside the one-hour window. Claims **55-65% at 1:3**, about +1.4R per trade — an
extraordinary claim and the most falsifiable thing in the methodology.

### The 2022 model
1. daily bias on D/4H before the session
2. mark the 00:00-03:00 NY range as reference liquidity
3. do not pre-position
4. sweep of that range **opposite to bias** (the Judas move) — 5/3/1m
5. MSS on 5/3/1m **in the bias direction**, decisive close
6. displacement leaving an imbalance
7. mark the PD array created during displacement
8. validate its premium/discount side relative to the swept range (15m)
9. wait for the retrace — do not chase
10. enter at the tap; stop beyond the swept extreme; target the opposite end of
    the swept range

Invalidated by: unclear daily bias, MSS failing after the sweep, too tight a
stop, printing outside London/NY killzones, or price never retracing.

Timeframes: Daily = bias, 1H = key levels, 15m = liquidity pools, 5/3/1m =
execution.

---

## The constraint every result runs into

Measured on 5-minute ES, 2021-2024:

| | points |
|---|---|
| median FVG gap width | **0.75** |
| median distance price → gap midpoint | 1.88 |
| **round-turn cost** | **1.02** |

**59.8% of gaps are narrower than one round turn.** Five-minute ES structures are
1-3 points; a retail round turn is 1.02. Any signal defined on that geometry is
sub-spread by construction.

So **a primitive can be real and untradeable at once**, and most here are. Report
significance and expectancy separately; a large z never implies a tradeable edge.

| signal | significance | expectancy vs 1.02 cost |
|---|---|---|
| sweep/run rule | z 10.24 | ~0.5 pt → **1:2** |
| sweep continuation (superseded) | z −5.22 | ~0.15 pt → 1:7 |
| FVG magnet | z +15.05 | ~0.08 pt → 1:13 |

---

## Testing rules learned the hard way

1. **Test the claim the concept makes**, not the one easiest to measure.
2. **Condition on the return** for every PD array. Formation is not the trigger.
3. **Match the control to the claim** — same width, same distance, same side of
   price. A control mirrored to the opposite side confounds with trend and
   flipped one result's sign.
4. **Exclude ties, never assign them.** An exact zero close-to-close move is 6.2%
   of events at one 5-minute bar. Assigning them silently moved a headline from
   −2.33 to −5.28, and made a decaying tie rate look like a decaying signal.
5. **Day-block bootstrap.** Detections cluster in a session and overlapping
   forward windows share bars; independence inflates every z.
6. **Pair the statistic when the design is paired.**
7. **Check window dependence** before trusting a detector count.
8. **Any edge above +5 points is a bug until the cause is found.**
9. **`P(edge > 0)` across null seeds is not significance** — it measures
   null-estimation noise. Use sampling error.
10. **The three-part rule:** `|z| > 3`, `n >= 5000`, **and replication on an
    independent timeframe.** Two headlines were retracted for want of it — an
    underpowered positive is not a weak positive, it is an unknown.
11. **Assert that env vars are actually read.** A run was wasted passing
    `SW_ENTRY` to a script that ignored it and silently re-measured the old
    population.
