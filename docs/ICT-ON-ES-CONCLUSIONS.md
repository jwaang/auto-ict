# What ICT concepts actually do on ES

A summary of the research recorded in `docs/BACKTEST-RESULTS-LOG.md`, written for
someone who has not read it. Every figure here traces to a numbered experiment.

Data: ES continuous, 1-minute, 2021-07-25 to 2024-12-31 for all screening and
selection. The 2026 holdout was never opened — see the last section.

---

## The two findings that generalise

### 1. "Zone" is a category error. What exists is a gradient.

ICT names specific bands and levels where price is supposed to react: the
**optimal trade entry** at 61.8-79% of a retracement, and **consequent
encroachment** at the 50% midpoint of a fair value gap. Both are claims that a
boundary is special.

Both are false in the same way, and the shape of the failure is identical.

| retracement depth | continuation edge (1m, h4) |
|---|---|
| <38.2% | **−2.48** (z −8.2) |
| 38.2-61.8% | +0.42 |
| **61.8-79% — the OTE band** | **+0.73** |
| 79-100% | **+1.68** (z +4.9) |
| >100% — "invalidated" | **+1.55** (z +5.2) |

| depth into a fair value gap | continuation edge (1m, h4) |
|---|---|
| near edge | −0.08 |
| 25% | +0.75 (z 6.2) |
| **50% — consequent encroachment** | **+0.82** (z 7.0) |
| 75% | +0.97 (z 7.9) |
| far edge | +0.96 (z 7.2) |
| >100% — "fully mitigated" | **+1.51** (z **10.6**) |

Neither named level is a peak. Both curves rise **monotonically with depth**, and
in both cases the region the methodology calls *invalidated* performs best. On
168,000-195,000 samples per level, replicated on a second timeframe. Experiments
45 and 46.

**And this explains why practitioners believe it.** Entering at consequent
encroachment really does beat entering at the near edge — +0.82 against −0.08.
Entering at 70% of a retracement really does beat entering at 30%. The experience
that produces the rule is real and repeatable. What is imaginary is the boundary
it gets attached to. The mechanism is mundane: the deeper price has retraced, the
more of the move remains to travel.

A practitioner who "confirms the zone works" is observing a true gradient and
attributing it to a false edge.

### 2. Every real effect is smaller than the spread

Measured on 5-minute ES:

| | points |
|---|---|
| median fair value gap width | **0.75** |
| median distance from price to gap midpoint | 1.88 |
| **round-turn cost** (spread + slippage + commission) | **1.02** |

**59.8% of fair value gaps are narrower than one round turn.** Five-minute ES
structures are 1-3 points. Any signal defined on that geometry is sub-spread by
construction, whatever its name and however significant.

The extreme case is Silver Bullet, whose prescribed stop — beyond the creating
candle's wick — is **0.75 points on 1-minute**. Its *risk unit* is smaller than
the cost of trading it, so cost is 1.36R per trade and break-even rises from 25%
to 59% before any question of edge. Experiment 47.

---

## The scoreboard

| claim | verdict | evidence |
|---|---|---|
| **Sweep vs run** — HTF bias selects reversal or continuation | **confirmed** | +5.57, z 10.24, n=10,108; replicated 1m/5m/15m; neutral-bias control flat (exp 40) |
| **FVG magnet** — price returns to rebalance | **confirmed** | +4.30 over matched control, z +15.05, n=43,536 (exp 36) |
| **Do not chase shallow retracements** | **confirmed** | −2.48, z −8.2, n=26,810 (exp 45) |
| **Weak FVGs are traps** | **confirmed** | −1.81, z −3.89, n=25,722 (exp 39) |
| **FVG springboard** — price continues from the gap | **refuted** | −0.5 to −1.1 below matched control, n=40,413 (exp 37) |
| **OTE zone** — 61.8-79% is optimal | **refuted** | monotone, not peaked; deeper bands better (exp 45) |
| **Consequent encroachment** — 50% is the reaction point | **refuted** | monotone; mitigated region best at z +10.6 (exp 46) |
| **Silver Bullet** — 55-65% at 1:3 | **refuted twice** | measured 21.94%, 21 SE from claim; stop < spread (exp 47) |
| **Premium/discount as a direction vote** | **refuted** | votes bearish 97% of the time in a rising market |
| **Order block reaction** | unknown | n=231-640, no consistent sign (exp 44) |
| **Breaker stronger than order block** | unknown | n=75-136 (exp 44) |
| **Blocks weaken with each retest** | unknown | n=214-612 (exp 44) |
| **The full 2022 sequence** | **unfalsifiable** | completes on 1.9% of setups; n=664 against 5,000 needed (exp 43) |

Before any of this, **73 whole-strategy configurations** were tested and none
cleared its break-even bar. That search was abandoned not because it ran out of
ideas but because the measurement could not resolve an edge even if one existed.

---

## What is real

Four claims survive at full power, and one of them is genuinely interesting:

**The sweep/run rule.** A failed break — price wicks a level and closes back
inside — continues in the probed direction when higher-timeframe structure agrees
with it, and the selector is bias rather than the candle. +5.57 points at z 10.24
on 10,108 samples, replicated at 5m and 15m, with a **flat neutral-bias cell**
where the methodology makes no prediction. That last part is the strongest
evidence in the programme: an effect that appears exactly where the theory says
it should and vanishes where it says nothing.

Earlier this was published with the opposite sign. That reading omitted the bias
condition entirely and pooled sweeps with runs — a mixture artifact, compounded
by a tie-handling bug that doubled its apparent size.

---

## Why none of it trades

**A directional edge is not a trading edge**, and the gap is larger than it looks.

The sweep/run rule gives +5.57 points of directional accuracy. Converted through
barriers with costs, it is worth about **+0.03R gross** (exp 41).

The reason: a direction test asks *is the close higher h bars later* — an
**endpoint**. A trade asks *does price reach +2R before −1R* — a **path**. Barrier
outcomes depend on the order levels are touched, not where the series ends, so a
55% chance of being up in fifteen minutes says very little about winning a race
between two barriers.

Every geometry tested confirms it. On the full multi-timeframe sequence, moving
the target from 0.26R to 3.31R took the win rate from 75% to 19% — almost exactly
what fair barriers predict — with the shortfall against break-even pinned near 8
points throughout (exp 43). The tradeoff is priced.

---

## What was never decided, and what it would take

The order-block family and the full sequence are **unknown**, not refuted. The
distinction matters.

ICT's complete setup — sweep, then structure shift, then retrace into the
displacement's gap — completes on **1.9% of qualifying setups**. Three and a half
years of 15-minute ES yields 178 samples; the multi-timeframe version reaches 664.
The floor for detecting a 1-4 point edge is 5,000.

**Powering it needs roughly 7.5 times the data — about 35 years of history — or
an instrument where the sequence fires far more often.** That is a number, not a
shrug. The sequence sits in a gap where it is frequent enough to trade and too
rare to prove, on the only timeframe where costs permit trading at all.

---

## The bugs, and the asymmetry worth remembering

Eight defects were found in this programme's own measurement code. **Seven made
results look better than reality.** None made them look worse.

| defect | what it did |
|---|---|
| session-end close required a 16:00 bar | positions held through holidays supplied **93% of gross profit** |
| entries taken at the cutoff hour | 31 trades opened and closed one bar later |
| `smc.ob()` keeps unmitigated blocks on a full frame | **97% win-rate artifact** — selection on the future |
| ties assigned to one side instead of excluded | a −2.33 headline published as −5.28 |
| order-block retests counted before confirmation | inflated the reaction by +8 to +18 |
| breaker retests counted before confirmation | held +14 while its siblings collapsed |
| sweeps measured with no bias condition | mixture artifact; published with the wrong sign |
| control zone mirrored across price | confounded with trend; flipped a result's sign |

That asymmetry is the transferable lesson. **A number that flatters the
hypothesis deserves suspicion before one that disappoints it.** Two rules caught
most of these: *any edge above +5 points is a bug until the cause is found*, and
*if a fix moves some arms and not others, the fix was not shared*.

### Two retractions

| published | on replication |
|---|---|
| concurrency cap 6: +2.24 on train | **−8.87** out of sample |
| exceptional FVG tier: +3.22 at n=1,197 | **−0.08** at n=5,241 |

Both were flagged as underpowered when published, and flagging was not enough.
The rule adopted afterwards: **`|z| > 3`, `n >= 5000`, and replication on an
independent timeframe.** Anything else is recorded as *unknown*, never as a weak
positive.

One refinement: the sample floor is for detecting **small** edges. Refuting
Silver Bullet's claim needed only n=720, because a 33-point gap is 21 standard
errors wide. Power depends on effect size, not on a fixed threshold.

---

## One lead, recorded and not chased

Continuation rises monotonically with retracement depth, and the **>79% band
gives +1.68 at z +4.9 on n=22,916** — the opposite of what ICT prescribes, which
is to treat that region as invalidation.

It was not tested against costs, deliberately. A +5.57 endpoint edge already
converted to +0.03R gross, so a third of that magnitude almost certainly converts
to nothing. Recorded here so the finding is not lost, with the reason it was not
pursued.

---

## What would have to be true

For any of this to trade on ES, one of:

- **Costs near 0.2 points rather than 1.02.** Institutional execution changes
  every arithmetic result in this document.
- **An instrument whose structures are large relative to its spread.** The
  constraint is a ratio, not a property of ICT.
- **A horizon long enough for the edge to outgrow the toll.** But the measured
  effects decay to nothing within two hours, so this one is closed on ES.

This is framed as "what would change the answer", not as encouragement. On ES at
retail cost, the answer is settled.

---

## Spans, and the holdout

- **2021-07-25 to 2024-12-31** — training. All screening and selection.
- **2025** — used twice as out-of-sample validation, and both times it did its
  job: the concurrency-cap candidate went from +2.24 on train to **−8.87** here
  (exp 32), and the inverted-bias test resolved here (exp 33). No cell in
  `logs/experiments.jsonl` runs past 2024-12-31; the 2025 runs were research
  scripts.
- **2026-01-01 to 2026-07-23 — never opened.** Nothing in this repository has
  read it.

The pre-registered rule was that the holdout is spent only on a candidate worth
validating. After 47 experiments there is none. That is a finding, not an
oversight, and it is stated here so nobody assumes it was forgotten.
