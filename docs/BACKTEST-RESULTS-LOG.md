# Backtest Results Log

Record of backtesting experiments, configurations, and findings.
Last updated: July 2026.

> ## Program conclusion, July 2026
>
> **On ES 15-minute data from 2021-07-25 to 2024-12-31, this mechanised ICT
> methodology is indistinguishable from a matched random-direction strategy
> before costs, and decisively untradable after them.**
>
> Sixty-eight configurations. The best cleaned directional result is **−0.22
> win-rate points** over thirty seeds at n=729, against a break-even bar of
> **+4.24**. Individual concepts sit at +0.2 (n=622) and +0.4 (n=142). No bias
> rule, trigger, geometry, stop width, timeframe or entry gate has cleared its
> own bar.
>
> Two structural findings explain why further search on this instrument is not
> worth running.
>
> **Costs are ~1.02 points per round turn and independent of position size**, so
> they are 10.9% of R at the observed 9.4-point stop. Break-even needs
> `cost_share / (1 + m)` of edge, about +4 points. Widening the stop lowers that
> (experiment 27) and so does coarsening the timeframe (experiment 30); neither
> creates edge, and a cheaper bar buys nothing when there is none to protect.
>
> **The statistical hurdle has bound in every cell ever run.** Three standard
> errors of the barrier win rate is +5.2 points at n=729, +8.7 at n=262 and
> +16.8 at n=72. Coarsening the timeframe lowers the economic bar and raises the
> statistical hurdle faster. Even at n=5000 the hurdle is +2.6, so an edge under
> about +3.8 is untradable and one under +2.6 is undetectable. A public retail
> methodology showing a clean +4-point directional edge on a liquid index future
> after costs would be surprisingly large.
>
> What this program did produce is a measurement harness that can be trusted:
> matched paired nulls, barrier-only scoring, cost accounting that reconciles by
> construction, and — since experiment 28 — exact agreement between the engine
> and the resolver used for every benchmark. Two published conclusions were
> wrong and were found by that harness rather than survived by it.
>
> **The 2026-01 to 2026-07 holdout has never been opened.** No cell has ever run
> past 2024-12-31. There is no candidate worth spending it on.
>
> Continuing requires a different instrument, or a different data source such as
> order flow. Neither is on disk.

> ## Every result below experiment 14 is superseded
>
> A July 2026 audit found seven bugs that change P&L. Numbers recorded before
> that date cannot be compared with numbers recorded after it, and the data
> files they were produced from are no longer on disk. Treat them as history.
>
> What changed:
>
> 1. **Contract stitching dropped back-month bars into the series.** The
>    front-month window was trimmed at one end only, so ESM5, ESU5 and ESZ5 all
>    kept bars from before they were front month. Those bars shared timestamps
>    with the true front month and the dedup picked between them with an
>    unstable sort. Any run over the Databento multi-contract file mixed two
>    contracts' prices.
> 2. **Rolls are now back-adjusted** (Panama). Before, each roll left a raw
>    calendar-spread step that the FVG and displacement detectors read as a gap.
> 3. **Session-end close fired for eight hours, not one.** `hour >= 16` is true
>    for ET hours 16 through 23, so positions opened in the evening were closed
>    one bar later as `SESSION_END` stubs.
> 4. **P&L had no contract multiplier.** Sizing was `risk$ / stop_points`,
>    i.e. fractional contracts at $1 a point. ES is $50 and MES is $5. Futures
>    now size to whole contracts, and a stop too wide to afford one contract is
>    counted as `unaffordable_skips` instead of being traded.
> 5. **Costs are on.** `SPREAD_POINTS = 0.50`, `SLIPPAGE_POINTS = 0.25`,
>    `COMMISSION_PER_CONTRACT = 1.25`. Everything above is gross of all three.
> 6. **Max drawdown is marked to market every bar.** It used to be derived from
>    an equity curve with one point per fill, so open-trade losses were invisible.
>    The circuit breaker now reads unrealized loss too.
> 7. **Daily and 4H bars follow the CME session.** They were anchored to UTC
>    midnight, so a "daily" bar closed at 19:00 ET in winter and 20:00 ET in
>    summer against a trading day that runs 18:00 to 17:00 ET. PDH/PDL, daily
>    bias and premium/discount were all computed across two sessions.
>
> Backtests also run about 4x faster — see the entry below.

---

## Experiment 44 — The order-block family, and two look-ahead bugs caught by the +5 rule (July 2026)

The order block, breaker and mitigation block, built to the four-condition
specification for the first time. Every order block previously measured here used
`smc.ob()`, which implements none of the four conditions — the liquidity grab,
the engulfment, the FVG or the MSS.

### The strict definition finds more, not fewer

| timeframe | `smc.ob()` full-frame | four-condition |
|---|---|---|
| 15m | 72 | **226** |
| 5m | 122 | **463** |
| 1m | — | **1,143** |

`smc.ob()` on a full frame keeps mainly *unmitigated* blocks and discards the
rest, so being stricter per candidate while keeping everything that passes yields
roughly three times as many.

**The engulfment is the binding condition.** At 15m it rejects 46,382 candidates
against 1,445 for the FVG and 825 for the MSS. Once a candle grabs the prior
extreme *and* closes fully beyond it, conditions 3 and 4 almost always follow —
they are largely consequences of the displacement rather than independent
filters. The specification reads as four requirements and behaves as about two.

### Two look-ahead bugs, both caught by the "+5 points is a bug" rule

The first pass returned +8 to +18 points with a textbook hierarchy — breaker >
order block > mitigation — replicated on both timeframes. It looked like the
specification vindicating itself.

**Bug one:** a block requires an FVG within 3 bars and an MSS within 10 bars
*after* the block candle, but the retest scan started at `i+2`. Reactions
occurring before the confirming shift were being counted, so the block was
selected using information that did not exist at the moment of entry. Fixed by
recording `confirmed_index` and requiring retests to follow it.

**Bug two, found because the fix worked unevenly.** After fixing bug one the
order block and mitigation effects collapsed while the breaker held at
+14.8/+15.1/+14.1. **One arm surviving a correction that should have touched all
three meant the correction was not actually shared.** `violated_with_shift`
returned the *violation* bar, but a breaker does not exist until the opposing MSS
confirms up to 12 bars later, so the same gap was still being counted.

| arm (1m) | first pass | bug one fixed | both fixed |
|---|---|---|---|
| order block 1st | +8.0 / +7.9 / +13.5 | +1.5 / +0.1 / +4.4 | +1.5 / +0.1 / +4.4 |
| mitigation | +0.2 / +9.4 / +8.9 | +6.4 / +4.3 / +6.0 | +6.4 / +4.3 / +6.0 |
| breaker | +17.7 / +7.3 / +12.0 | +14.8 / +15.1 / +14.1 | **+8.5 / −2.2 / +0.6** |

### The verdicts

| concept | n (5m / 1m) | 5m | 1m | verdict |
|---|---|---|---|---|
| order block, 1st retest | 231 / 640 | −1.3 / +10.8 / −5.7 | +1.5 / +0.1 / +4.4 | **unknown** |
| mitigation, 2nd+ retest | 214 / 612 | −3.0 / +5.3 / +0.1 | +6.4 / +4.3 / +6.0 | **unknown** |
| breaker, flipped | 75 / 136 | +18.2 / +0.0 / +9.7 | +8.5 / −2.2 / +0.6 | **unknown** |

No arm holds a consistent sign across horizons *and* timeframes, and every sample
is far below the 5,000 floor. Recorded as unknown exactly as registered before
the numbers existed, with sample count as the headline rather than effect.

The honest reading beyond "unknown": after removing both look-aheads there is **no
evidence of an effect** in any of the three, and the stated hierarchy — breaker
stronger than order block, blocks weakening with each retest — does not survive
either. But the samples cannot rule one out.

### The pattern across this programme

This is the third look-ahead-shaped defect found here, after `smc.ob()`'s
unmitigated-survivor artifact at 97% and the session-end holiday carry worth 93%
of gross profit. **All three made results look better than reality, never worse.**
That asymmetry is the reliable signal: a number that flatters the hypothesis
deserves suspicion before a number that disappoints it.

---

## Experiment 43 — The full multi-timeframe sequence, and the geometry is fair (July 2026)

The first faithful test of the methodology as specified: 15-minute context for
bias, liquidity and the stop; 1-minute execution for the MSS and the entry.
Experiment 42 ran every leg on one timeframe, which both starved the sample and
removed the mechanism — entering and exiting on the same scale cannot produce the
large R:R the methodology claims.

### The structure did what it was built to do

| | exp 42 arm C | exp 43 |
|---|---|---|
| fill rate | 1.9% | **7.1%** |
| n | 178 | **665** |
| median cost/R | — | **0.140** |

Both registered predictions held: the finer execution leg completes the sequence
far more often, and the coarse stop keeps cost/R low despite a fine-grained entry.
`research/mtf_join.py` handles the two-frame join with 8 tests, the key one
asserting an execution bar at the context bar's close is **excluded** — using it
would react to a close with a bar that printed before that close existed.

### The first attempt had a broken target, and the funnel showed it

Median R:R came out at **0.27** — risking 7.27 points to make 2 — because
`next_liquidity` took the *nearest* level while the stop sat beyond the coarse
swept extreme. Target and stop were on different scales. That produced a 74.81%
win rate needing 89.61%.

The source never says nearest: it says the next **significant** draw, the 2022
model says the opposite end of the swept range, Silver Bullet says typically 1:3.
So a minimum-R:R floor was added to express "significant", and swept rather than
chosen, since which level qualifies is a specification ambiguity.

### The geometry is fair at every target distance

| min R:R | median R:R | win rate | break-even needs | gap | mean net R | 95% |
|---|---|---|---|---|---|---|
| 0.0 | 0.26 | 75.04% | 90.64% | −15.6 | −0.115 | [−0.240, +0.032] |
| 1.0 | 1.28 | 42.23% | 50.04% | −7.8 | −0.081 | [−0.262, +0.128] |
| 1.5 | 1.79 | 33.40% | 40.91% | −7.5 | −0.038 | [−0.238, +0.187] |
| 2.0 | 2.27 | 25.79% | 34.87% | −9.1 | −0.048 | [−0.253, +0.184] |
| 3.0 | 3.31 | 18.67% | 26.43% | −7.8 | −0.028 | [−0.264, +0.226] |

**Mean net R is negative at all five geometries.** Moving the target from 0.26R to
3.31R takes the win rate from 75% to 19%, which is close to what fair barriers
predict, and the shortfall against break-even stays pinned near 8 points
throughout. Nothing about the target choice rescues it — the tradeoff is priced.

The sharper reading: the win rate sits below even the **gross** break-even of
`1/(1 + R:R)` at every geometry — 18.67 against 23.2 at the widest, 33.40 against
35.8 in the middle. So this is not only a cost story. The entry performs at or
slightly under what the barrier geometry alone implies.

### It still cannot be powered, and that was the pre-registered stop

n=664 at a 7.1% fill rate, against a floor of 5,000 — short by a factor of 7.5.
Every interval spans zero.

The decision to stop here was made **before** these numbers, precisely so it
would not be made while looking at them. The alternative on the table was
widening the MSS and retrace windows until the fill rate cooperated, and that was
ruled out in advance: it stops being the sequence the source describes, and
tuning a window until n suffices is a selection process on the same data — the
mechanism behind both retractions in this log.

What can honestly be said: across five independent target geometries the point
estimate is negative every time and the win rate never reaches break-even, which
is evidence against the sequence being profitable as specified; and the sample is
too small for any of it to be significant on its own.

**ICT's full setup cannot be validated or refuted on five years of ES at a
timeframe where costs permit trading.** Powering it needs roughly 7.5 times the
data — about 35 years of 15-minute history — or an instrument where the sequence
fires far more often.

---

## Experiment 42 — The prescribed entry points the right way and cannot be powered (July 2026)

Experiment 41 left one lever untested. Everything measured so far entered at the
probe bar, which the source explicitly calls not a trade; the prescribed entry
waits for a lower-timeframe MSS and enters on the retest of the PD array created
by the displacement leg. That is a **path intervention** — it moves entry price
relative to a fixed invalidation level, changing R:R directly rather than
changing direction accuracy.

Three arms, identical stop anchored on the probe candle, so they differ only in
entry. 15-minute, training span, cell = bias agrees.

### MSS built to the specification

`research/ict_mss.py`, with 14 tests. A swing broken by a **body close** past the
extreme — "a wick poke is not an MSS" — where the breaking candle is a
displacement. `smc_adapter.detect_bos_choch` requires neither, so everything
previously measured through it was CHoCH at best.

### The results

| arm | disp 2.0 | disp 1.5 | disp 1.0 | disp 0.75 | fill rate |
|---|---|---|---|---|---|
| **A** probe bar | −0.127 | −0.127 | −0.127 | −0.127 | 100% |
| **B** MSS close | −0.228 | −0.004 | −0.029 | −0.063 | 2.4-14.6% |
| **C** PD array retest | — | — | **+0.277** | **+0.096** | **1.9-2.4%** |

Arm A reproduces experiment 41 to four decimals (−0.1268), which is the control
confirming the new harness measures the same population before the entry rule
changes.

**The ordering moves as predicted.** A → B → C runs −0.127 → about zero →
positive, at every threshold where C is measurable. That is the registered
mechanism: confirmation helps somewhat, the retest price helps more, because
entering nearer a fixed stop raises R:R.

### And it cannot be confirmed

Arm C is **n=178 at a 1.9% fill rate**, and every interval spans zero — the best
cell is [−0.078, +0.565]. Against the pre-registered rule of `|z| > 3`,
`n >= 5000` and independent-timeframe replication, it misses the sample floor by
a factor of 28.

**This is recorded as unknown, not as a weak positive.** It has the exact shape of
the two results already retracted here: the cap-6 cell at +2.24 that became −8.87
out of sample, and the exceptional FVG tier at +3.22 that became −0.08 under
power. Both were attractive small-n cells with wide intervals, and both were
reported before replication.

The displacement threshold was swept rather than chosen, because the source's
"ideally creates a fair value gap" makes it a specification ambiguity rather than
a parameter. All four settings are above. Arm C is positive at both thresholds
where it has enough samples to report, which is mildly reassuring and nowhere
near sufficient.

### The structural finding

**ICT's full prescribed sequence is too rare to validate on available data.**

It requires a sweep, then an MSS within twelve bars in the right direction, then a
retrace into the displacement leg's FVG. That chain completes on **1.9% of
qualifying setups**. Three and a half years of 15-minute ES yields 178 samples
where 5,000 are needed.

Powering it would take roughly a hundred years at this timeframe, or a move to
1-minute data where cost drag is 0.515R and already sank arm A there. So the
sequence sits in a gap: **frequent enough to trade, too rare to prove**, on the
only timeframe where costs permit trading at all.

That is a different kind of negative from the rest of this log. The earlier
results were measured and refuted. This one is unfalsifiable with the data
available, and saying so is the honest end of it.

---

## Experiment 41 — The sweep/run edge is an endpoint edge, and does not survive barriers (July 2026)

Experiment 40's sweep/run result is the only finding here to pass `|z| > 3`,
`n >= 5000` and independent-timeframe replication. This applies geometry and
costs to it. Stops follow the source — beyond the candle extreme that invalidates
the trade, buffered in ATR so they scale — with targets at multiples of that risk.

### Every cell loses, and cost is no longer the reason

| cell | n | median risk | cost/R | mean net R | 95% interval | implied gross |
|---|---|---|---|---|---|---|
| 15m all forms | 9,296 | 8.01 pt | 0.127 | **−0.095** | [−0.194, +0.004] | **+0.03** |
| 15m sweep form | 1,083 | 6.50 pt | 0.157 | −0.159 | [−0.292, −0.027] | −0.002 |
| 5m sweep form | 3,103 | 3.87 pt | 0.264 | −0.307 | [−0.355, −0.259] | −0.043 |
| 1m sweep form | 10,108 | 1.98 pt | 0.515 | −0.684 | [−0.731, −0.640] | −0.169 |

Widening the stop did what it was supposed to: **cost drag fell from 0.515R at
one minute to 0.127R at fifteen**, the lowest this programme has reached. It did
not help, because gross expectancy is only about **+0.03R**.

### An endpoint edge is not a path edge

This is the lesson, and it is the second time it has appeared.

The direction test asks: *is the close higher h bars later?* That is an
**endpoint**. A trade asks: *does price reach +2R before −1R?* That is a **path**.
A 55% chance of being up in fifteen minutes says very little about winning a race
between two barriers, because the barrier outcome depends on the order in which
levels are touched, not on where the series ends.

So a +2.63 to +5.57 point directional edge — real, replicated, significant at
z 10.24 — converts to roughly +0.03R gross. Experiment 35 found the same for the
older sweep reading. **Directional accuracy at a fixed horizon should not be
reported as evidence a strategy is close to viable**, and earlier entries in this
log that estimated tradeability from win-rate edge alone (the "1:2 against costs"
figure) were doing exactly that. The correct estimate is the barrier measurement,
and it is 1:4 gross, not 1:2.

### What survives

The finding itself stands: the sweep/run rule is a real, replicated property of
ES price. ICT's claim that higher-timeframe bias selects between reversal and
continuation is **correct**, and it is the only ICT claim this programme has
confirmed at full power.

What does not follow is that it can be traded with these entries and exits. The
15m all-forms interval reaches +0.004 at its top, so break-even is at the extreme
edge of plausibility, and the point estimate is negative in all twelve geometries
tested at every timeframe.

Next: the entry actually prescribed. All of the above enters at the probe bar,
which the source explicitly calls not a trade — the prescribed entry waits for a
lower-timeframe MSS and enters on the PD array retest. Whether confirmation
changes the *path* statistics, as opposed to the endpoint ones, is the open
question and is the first thing this programme has had a mechanism-level reason
to expect might differ.

---

## Experiment 40 — A tie-handling bug, and the sweep/run rule replicating on three timeframes (July 2026)

Two corrections and the best-supported result this programme has produced.

### The tie bug, which inflated experiments 34-37

Every directional test wrote `(close[t+h] - close[t]) * sign > 0`. An exact zero
close-to-close change is **6.2% of events at one 5-minute bar**, decaying to 1.2%
by 24 bars, and that formulation silently assigns every tie to one side.

| tie treatment | reversal rate, sweep-form, h=1 |
|---|---|
| ties counted as failures (as published) | 44.70% |
| ties counted as wins | 50.93% |
| **ties excluded (correct)** | **47.67%** |

So experiment 34's headline of −5.28 at z −11.68 is really **−2.33 at z −5.22**,
inflated about twofold. Worse, the "decay with horizon" that made the result look
like a real microstructure effect partly tracked the **tie rate** decaying from
6.2% to 1.2%, not the signal.

It also touches experiment 37, where "continuation runs 47-49%, below a coin flip
at every horizon" becomes roughly 50.6% with ties excluded — *at* the coin flip.
The paired difference against the control survives, because both sides carried the
same bias, but that absolute claim was an artifact.

Ties are now excluded rather than assigned.

### The sweep/run rule, which was never applied

ICT separates a liquidity **sweep** (wick through, close back inside, reversal)
from a **run** (close beyond, sustained displacement, continuation), and the rule
choosing between them is not mechanical:

> "If the higher-timeframe direction agrees with the side that just got swept,
> expect a run; if it disagrees, expect a sweep."

Experiments 34 and 35 applied no bias condition and predicted reversal for every
event. That is a mixture, and the −2.33 above is what a mixture produces.

Splitting on bias agreement, with edge measured against **what ICT predicts for
that cell**, so positive means the methodology is right (5-minute):

| cell | n | h1 | h2 | h4 | h12 | h24 |
|---|---|---|---|---|---|---|
| bias agrees → expect continuation | 28,004 | +0.99 (z 3.24) | +1.53 (z 3.94) | +1.85 (z 3.69) | +2.48 (z 3.10) | +3.57 (z 3.27) |
| bias disagrees → expect reversal | 22,880 | +0.72 | +1.05 | +1.43 | +1.92 | +2.41 |
| **neutral bias** | 55,330 | +0.13 | +0.32 | +0.21 | +0.51 | +0.47 |

**The neutral cell is flat at every horizon (z < 1.2).** That is an internal
control nobody designed as one: where the methodology makes no prediction, there
is no effect. A spurious pattern would not respect that boundary.

### The specific cell, replicated on three timeframes

Sweep form — wick through, closed back inside — **with bias agreeing**, so a
failed break in the direction of the prevailing structure:

| timeframe | n | h1 | h4 | h24 |
|---|---|---|---|---|
| **1m** | **10,108** | **+5.57 (z 10.24)** | **+4.92 (z 8.31)** | **+3.72 (z 4.70)** |
| 5m | 3,103 | +3.75 (z 3.99) | +3.45 (z 2.97) | +2.33 |
| 15m | 1,083 | +5.00 (z 3.12) | +3.31 | +2.47 |

Same sign, comparable magnitude, significant at every horizon on 1-minute where
n clears 5,000. z 10.24 survives a Bonferroni correction over all 30 cells
examined, which needs about 3.4.

It also passes the three-part rule adopted after two retractions: `|z| > 3`,
`n >= 5000`, **and replication on an independent timeframe**. It is the first
result in this programme to do so.

The run-form cell is *weaker* than the sweep-form cell (−0.04 to +1.40 on 1m), so
the effect is specific rather than smeared across all liquidity events.

### Still probably not tradeable, and by how much

A +5.57-point edge is 55.6% directional accuracy. At the two-hour horizon on 5m
the edge is +3.57 against an expected absolute move around 7 points, so roughly
**0.5 points of expectancy against 1.02 points of round-turn cost.**

That is a ratio of about **1:2**, against 1:7 for the old sweep reading and 1:13
for the FVG magnet. The closest anything has come, and still under water. The next
test is whether barrier geometry closes a two-fold gap — it has not closed a
seven-fold one before.

---

## Experiment 39 — The exceptional-tier reaction does not replicate (July 2026)

Experiment 38 reported the tier reaction ordering as −3.07, −0.35, +3.22 and
called it the first ICT claim to be confirmed rather than refuted, while flagging
that the top tier was n=1,197 at z +1.55 and needed power. **The power test says
no.**

Same measurement on 1-minute bars over the same span, 214,792 gaps against
43,536, giving the exceptional tier 5,985 detections instead of 1,402:

| tier | n (reaction) | h=1 | h=4 | h=12 |
|---|---|---|---|---|
| weak | 25,722 | **−1.81** (z −3.89) | **−1.77** (z −3.91) | −1.01 |
| quietly strong | 165,648 | −0.22 | **−0.93** (z −4.87) | **−0.67** (z −3.65) |
| **exceptional** | **5,241** | **−0.08** | −0.31 | −1.05 |

**+3.22 became −0.08 with 4.4 times the samples.** It was a small-sample
artifact. The retraction is the result: experiment 38's headline does not stand,
and no tier shows a positive reaction at adequate power.

### What does replicate

**Weak FVGs are traps, and now significantly so.** −1.81 at one bar and −1.77 at
four, both z about −3.9 on n=25,722. The source's advice to discard them is
correct. It is advice about what to avoid, not something to trade.

**The magnet strengthens with tier**, on both timeframes:

| tier | magnet 5m | magnet 1m |
|---|---|---|
| weak | +4.36 | +3.93 (z 13.17) |
| quietly strong | +4.16 | +6.00 (z 26.76) |
| exceptional | +5.35 | **+6.37** (z 9.08) |

A stronger imbalance pulls harder, and exceptional is strongest at both
resolutions. That is a genuine, replicated, correctly-ordered effect — and it is
still a claim about where price goes, not about expectancy.

### The lesson, again

Experiment 32 selected the best of a three-cell cap curve and it reversed out of
sample. Experiment 38 read two positive cells out of nine at n=1,197 and they
reversed under power. Both were flagged as underpowered when published and both
went the way the flag suggested.

The rule that keeps being re-learned: **an underpowered positive is not a weak
positive, it is an unknown.** Report it as unknown.

---

## Experiment 38 — FVG strength tiers (superseded by experiment 39) (July 2026)

> **The headline of this entry was retracted.** The exceptional-tier reaction of
> +3.22 did not replicate at higher power — see experiment 39, where it is −0.08
> on 4.4x the samples. The tier *magnet* ordering below does replicate.

Experiments 36 and 37 pooled all 43,536 gaps. The source separates them into
three mechanical tiers and says weak ones are traps to discard while exceptional
ones react "almost always violently and immediately", so pooling averages the
category to throw away with the category to trade.

`research/fvg_quality.py` classifies from the three candles plus the one before
them. Indexing verified empirically rather than assumed: `candle_index` points at
the **third** candle, since the patched detector emits after candle 3 closes, so
the displacement candle is `idx - 1` and the reference candle is `idx - 3`.

### Geometry alone is not enough to define "exceptional"

A first pass used only candle geometry — candle 2 breaks the prior candle's
range, candle 3 extends beyond candle 2. That labels **72.1%** of gaps
exceptional, which cannot describe institutional commitment. Making a new extreme
is a low bar on a trending 5-minute chart.

The source also requires a substantial body and minimal wicks on the middle
candle, so "exceptional" now additionally requires that candle to *be* a detected
displacement (body > 2x ATR). That moves the split to weak 9.2%,
quietly strong 87.5%, **exceptional 3.2%** — 1,402 gaps, and a plausible rarity.

### The tiers order exactly as claimed

| tier | n | magnet (fill vs control) | reaction h=1 | h=4 | h=12 |
|---|---|---|---|---|---|
| weak | 4,018 | +4.36 (z 5.69) | **−3.07** | −0.83 | +0.65 |
| quietly strong | 38,107 | +4.16 (z 13.37) | −0.35 | −0.60 | −0.89 |
| **exceptional** | 1,401 | **+5.35** (z 3.63) | **+3.22** | +0.31 | **+3.18** |

**The h=1 reaction is monotone in the predicted direction: −3.07, −0.35, +3.22.**
Weak gaps are blown through, exceptional gaps react. That is what the source
claims, and it is the first time in this programme that an ICT claim has been
confirmed rather than refuted.

The magnet holds in every tier and is strongest for exceptional (+5.35), which is
also consistent — a stronger imbalance pulls harder.

### What this does not yet establish

Exceptional is n=1,197 for the reaction test at z +1.55 and +1.53. **Suggestive,
not significant**, against a threshold of 3. Two positive cells out of nine
examined, so they are also the best of nine.

The stronger evidence is the *ordering* rather than any single cell, because it
was predicted in advance by the source and appears across three independent
populations. But an ordering with an underpowered top tier is a reason to get
more samples, not to conclude.

Note also what did not change: the pooled results from experiments 36 and 37 both
survive the split. The magnet is real in all tiers, and the reaction is negative
in the two tiers holding 96.7% of gaps. The tier taxonomy does not overturn
those; it isolates a small subset that behaves differently.

---

## Experiment 37 — The FVG is a magnet, not a springboard (July 2026)

The FVG claim has two parts: price retraces into the gap, **and then continues in
the gap's direction**. Part one was confirmed in experiment 36. Part two is the
tradeable half and had never been tested, because every earlier measurement
started at the gap's *formation* rather than at the *return*, which is the actual
trigger.

Measured on 5-minute ES over the training span. 43,536 gaps, of which **40,413
were returned to**, each compared against a geometry-matched control zone that
price also returned to — otherwise the comparison measures "does price come
back" rather than "does this zone work".

| horizon | continuation after return | matched control | difference | z |
|---|---|---|---|---|
| 1 | 47.46% | 47.97% | −0.50 | −1.31 |
| 2 | 47.98% | 48.56% | −0.58 | −1.54 |
| 4 | 48.40% | 49.23% | −0.84 | −2.28 |
| 6 | 48.66% | 48.97% | −0.31 | −0.85 |
| 12 | 48.71% | 49.83% | **−1.12** | **−2.99** |
| 24 | 49.22% | 49.92% | −0.70 | −1.92 |

**Every difference is negative.** The absolute level was originally reported as
"47-49%, below a coin flip at every horizon" — that part was a tie artifact and is
withdrawn. Exact-zero close-to-close moves were counted as non-continuation; with
ties excluded the rate is about 50.6%, at the coin flip. **The paired difference
against the control survives**, because both sides carried the same bias, so the
finding below stands and only the absolute claim was wrong. See experiment 40.

So the two halves of the FVG claim separate cleanly:

| claim | result |
|---|---|
| price returns to the gap to rebalance | **holds**, +4.30 points over control, z +15.05 |
| price then continues in the gap's direction | **fails**, −0.5 to −1.1 against control, never above 50% |

**The FVG is a magnet, not a springboard.** Price does come back to the
imbalance — that part of the methodology describes something real. It simply
does not bounce from it. It arrives and keeps going.

That is the more useful negative result, because it is specific. An entry model
built on "wait for the retracement into the FVG, then trade the continuation" is
trading the wrong half of a real phenomenon: the reliable half gets your limit
order filled, and the unreliable half is supposed to pay for it.

### Consequent encroachment, weakly positive and not yet trusted

Splitting the returns by depth: those reaching the 50% midpoint continue
+1.62, +1.20, +0.02, +0.71, +1.25 and +0.95 points more often than those touching
only the near edge.

Consistently positive but small, with no interval computed, and plausibly an
artifact — a return that reaches the midpoint has by construction travelled
further, so the split conditions on movement rather than on the level. It needs a
test with depth as the only variable before it counts as anything.

---

## Experiment 36 — Both real signals are sub-spread, and the reason is scale (July 2026)

The magnet claim strengthens at a shorter window, which is the right shape: with
a long enough lookahead everything fills and the control catches up.

| lookahead | real fill | control | paired difference | z |
|---|---|---|---|---|
| 48 bars | 89.99% | 85.69% | **+4.30** [+3.73, +4.86] | **+15.05** |
| 96 bars | 92.88% | 90.35% | +2.53 [+2.06, +3.01] | +10.32 |

So the FVG magnet is real and monotone. Then the question that decides it.

### The median gap is narrower than the cost of trading it

Measured over 43,536 FVGs on 5-minute ES across the training span:

| | points |
|---|---|
| median gap width | **0.75** |
| median distance from price to gap midpoint | 1.88 |
| **round-turn cost** | **1.02** |

**59.8% of gaps are narrower than one round turn.** 26.2% have their midpoint
closer to price than the cost itself, and 52.4% are within two round turns.

The marginal edge from the magnet is 4.3 percentage points of fill probability
over a matched control, applied to a median 1.88-point target: about 0.08 points
of expectancy against 1.02 points of cost.

### Both confirmed signals fail the same way

| signal | significance | expectancy | cost | ratio |
|---|---|---|---|---|
| sweep continuation | z −11.68, n=12,413 | ~0.15 pt | 1.02 pt | 1 : 7 |
| FVG magnet | z +15.05, n=43,536 | ~0.08 pt | 1.02 pt | 1 : 13 |

### This is a statement about scale, not about ICT

Five-minute ES structures have a characteristic size of roughly one to three
points — a median gap of 0.75, a median target distance of 1.88. A retail round
turn is 1.02 points. **Any signal defined on that geometry is sub-spread by
construction**, whatever its name and however significant it is.

That reframes every earlier result in this log. Seventy-three configurations
failed not because ICT primitives are meaningless — two of them are real at
z > 10 — but because the effects they describe live below the transaction floor.
The search was never going to find a configuration that fixed that, because no
arrangement of sub-spread signals produces a super-spread strategy.

It also predicts, rather than assumes, that the remaining primitives will fail:
CE reaction levels, OTE depths, order block and breaker retests are all defined
on the same five-minute geometry and therefore inherit the same ratio.

---

## Experiment 35 — The sweep signal is real, and smaller than the spread (July 2026)

Experiment 34 found a genuine directional signal: after a sweep, price continues
rather than reverses, 55.3% at five minutes, z -11.68. This applies geometry and
costs to 12,413 sweeps over the training span, entering in the continuation
direction, resolved on 1-minute data through the same first-touch logic and
16:00 cutoff as every other measurement here.

### Every geometry loses

| stop | cost/R | best mean net R | 95% interval | implied gross edge |
|---|---|---|---|---|
| 3 | 34.0% | −0.3404 | [−0.3538, −0.3269] | ~0.000 |
| 5 | 20.4% | −0.1870 | [−0.2022, −0.1726] | +0.017 |
| 8 | 12.8% | −0.1080 | [−0.1241, −0.0911] | +0.020 |
| 12 | 8.5% | −0.0812 | [−0.0976, −0.0640] | +0.004 |

All sixteen cells negative, every interval excluding zero, best −0.0812R at a
12-point stop. Mean net R improves monotonically as the stop widens, exactly
tracking `1.02 / stop`, which is the signature of a result driven by cost drag
rather than by anything in the signal.

### The reason is magnitude, not direction

Subtracting the known cost drag leaves a gross edge of **+0.00 to +0.02R**. The
direction edge is real but almost absent once expressed in R.

Over five minutes ES moves on the order of ±1.5 points. A 55/45 split on that is
about 0.15 points of expectancy. One round turn costs **1.02 points**. The signal
is smaller than the spread by roughly seven times.

That is the cleanest statement this program has produced. **A genuine market
inefficiency exists, is overwhelmingly significant at z −11.68 on n=12,413, and
is too small to transact on.** Nothing about strategy construction changes it:
the edge decays to nothing by two hours, so it cannot be held for long enough to
outgrow the spread, and it is too small at five minutes to pay for crossing it.

### What this closes

The primitive programme has now answered its own question. Of the primitives
carrying directional claims, the sweep is the strongest and it is
non-transactable. The FVG magnet claim holds (+2.53 points, z +10.32) but is a
statement about where price goes, not about expectancy — a limit entry at the
gap gets filled, which is not the same as winning.

---

## Experiment 34 — Two real findings: the FVG magnet holds, and sweeps predict the opposite of what ICT says (July 2026)

The first properly-controlled positive results in this program, on 5-minute ES
over 2021-07-25 to 2024-12-31. One sample per detection rather than per trade,
so n runs to tens of thousands and the instrument is finally sharper than the
effect. Day-block bootstrap intervals throughout.

### The FVG magnet claim holds

ICT says price returns to an imbalance to rebalance. Tested against a control of
identical width and identical signed offset from price, anchored at a random
other bar, so geometry is held constant and only the imbalance is tested.

| | fill rate within 96 bars |
|---|---|
| real FVGs | **92.88%** |
| matched control | 90.35% |
| **paired difference** | **+2.53 points, CI [+2.06, +3.01], z +10.32** |

n=43,519 over 1,069 days, median time to fill 1 bar. The paired statistic is the
right one — real and control are matched per gap, so comparing two separate
intervals is cruder.

At 15m the same test gives +0.54 with overlapping intervals on n=15,584, so the
effect is resolution-dependent and only clear at fine granularity.

**This does not make the FVG tradeable.** A 93% fill rate against a 90% control
is a statement about where price goes, not about making money net of costs, and
"price returns to the gap" is exactly what a limit entry at the gap needs — it
says the entry gets filled, not that it wins.

### Liquidity sweeps predict continuation, not reversal

The reference calls the sweep "the single most important pre-condition for an
ICT entry" and expects reversal after it. Measured over 12,413 sweeps:

| horizon | reversal rate | edge | z | half 1 / half 2 |
|---|---|---|---|---|
| 1 bar (5 min) | 44.72% | **−5.28** | **−11.68** | −4.19 / −6.37 |
| 2 | 46.10% | −3.90 | −7.72 | −2.95 / −4.86 |
| 3 | 46.46% | −3.54 | −6.92 | −2.66 / −4.42 |
| 4 | 47.07% | −2.93 | −5.64 | −2.14 / −3.71 |
| 6 (30 min) | 46.95% | −3.05 | −5.27 | −2.21 / −3.89 |
| 12 | 48.76% | −1.24 | −2.00 | −0.64 / −1.84 |
| 24 | 49.84% | −0.16 | −0.24 | −0.26 / −0.06 |
| 48 | 50.40% | +0.40 | +0.60 | +0.20 / +0.60 |

**The sign is the finding.** A reversal rate of 44.72% means continuation happens
55.28% of the time. After price wicks above a prior high and closes back below
it — a failed breakout, ICT's canonical sell trigger — price goes **up** 55% of
the time over the next five minutes.

Four things make this hard to dismiss: z −11.68 at the shortest horizon, monotone
decay to nothing by 24 bars, both time halves agreeing in sign and rough
magnitude at every horizon, and a balanced 47.5% bullish split so it is not the
index drift.

It also explains why 15m saw nothing: its shortest tested horizon is 60 minutes,
already past the decay.

### What is not yet established

**That any of this is tradeable.** These are close-to-close direction counts with
no barriers, no costs and no position sizing. A rough check says the edge is
probably too small: +5.28 points at a five-minute horizon over a typical ~3-point
range is about +0.3 points of expectancy gross, against 1.02 points of round-turn
cost. At 30 minutes it is roughly +0.5 against the same 1.02.

So the honest statement is that **a real directional signal exists and points the
opposite way to the methodology built on it**, and that the same cost wall which
closed every earlier experiment still stands in front of it. The next test is
whether any geometry converts a 55/45 five-minute edge into positive expectancy
after costs.

### Method note

The paired difference matters. An earlier version compared two separate
confidence intervals and an even earlier one used a control mirrored to the
opposite side of price, which confounded the test with trend and showed FVGs
filling *less* than control. Holding the side constant and shuffling only the
time changed −0.91 to −0.18 on the smoke sample, and the paired statistic at
full scale gives +2.53.

---

## Correction — the primitive test asked a question ICT does not make (July 2026)

The commit that added `research/primitive_information.py` recorded "the FVG
carries no directional information" from n=4418. **The measurement is sound and
the conclusion is aimed at the wrong claim.**

An FVG is not a directional signal and ICT does not say it is. Both the repo's
own reference and the wider literature are explicit: an FVG marks an imbalance
that *price tends to return to in order to rebalance*, and the Consequent
Encroachment at its 50% midpoint is a **reaction level**. It is a location, not
a reason to trade. `docs/ICT_Trading_Strategies_Combined_Research.md` places the
FVG at step 4 of the Universal Setup Structure — the **entry model** — after
bias, after the liquidity objective, and after the trigger.

So "does price rise after a bullish FVG forms" was never an ICT claim, and
measuring it flat neither supports nor refutes the methodology.

The directional claims live elsewhere, and the same reference is blunt about
which: of the liquidity sweep it says **"this is the single most important
pre-condition for an ICT entry. Without a sweep, the setup is incomplete."**

Restated test programme, by claim type:

| primitive | what ICT actually claims | correct test |
|---|---|---|
| Liquidity sweep | reversal after a stop hunt | reversal rate against chance |
| MSS / CHoCH | trigger confirming a new direction | continuation after a sweep |
| sweep → MSS → entry | the setup is the *sequence* | does ordering beat its parts |
| FVG | magnet; price returns to rebalance | fill rate against matched random zones |
| FVG CE | reaction level at the 50% midpoint | reversal rate at CE against a random level |
| OB, Breaker, IFVG | location to enter from | reaction rate on retest |
| OTE | better entry depth | 61.8-79% against other retracement depths |

The one result that stands from that commit is the **order block finding**: a
full-frame pass finds 36 OBs in a year where windowed passes find 243, and the
survivors are mainly unmitigated ones — an order block price never traded back
into, which is selection on the future. That invalidated a 97% win rate and the
mechanism is real regardless of which claim is being tested.

---

## Experiment 32 — The concurrency cap is not a lever, and 2025 is significantly negative (July 2026)

Five cells, ~100 min. `MAX_CONCURRENT_POSITIONS = 3` had never been varied — zero
occurrences in `logs/experiments.jsonl` — and was bound at import time in
`trading/risk.py`, the third constant found in that state. Now sweepable.

### The power argument that motivated this was wrong

The rejection funnel showed "Max concurrent positions reached" 912 times against
807 trades taken, which suggested raising the cap would roughly double the book
and drop the statistical hurdle below the economic bar for the first time.

**It does not. The funnel counts bar-level rejections, not distinct
opportunities** — the same signal is re-rejected on every bar while the slots
stay full. Raising the cap from 3 to 25 added about 130 trades, not 900, and the
statistical hurdle never fell below the economic bar at any cap.

That misreading is recorded because the funnel is the natural place to look for
"what is blocking trades", and it will mislead the same way again.

### On the training span the edge moved, and it was noise

| cap | trades | barrier n | WR | edge | z | econ bar | stat hurdle | gross | net |
|---|---|---|---|---|---|---|---|---|---|
| 3 (baseline) | 807 | 729 | 33.33 | −0.22 | −0.13 | 4.24 | 5.24 | +$5,030 | −$52,113 |
| **6** | 938 | 847 | 36.01 | **+2.24** | 1.36 | 4.35 | 4.95 | +$12,372 | −$51,640 |
| 12 | 897 | 793 | 34.30 | +2.09 | 1.24 | 4.14 | 5.06 | −$3,974 | −$64,397 |
| 25 | 935 | 821 | 34.10 | +1.47 | 0.89 | 4.02 | 4.96 | −$4,794 | −$66,755 |

Cap 6 was the best cell ever measured in this program: gross +$12,372 and an
edge of +2.24. It was still not a result — z 1.36 against a threshold of 3, and
+2.24 against an economic bar of +4.35. The edge also declined monotonically
with the cap, which fits noise around zero better than a real optimum at 6.

`P(edge > 0) = 100%` appears again at every cap and again means nothing: it is
spread across null seeds, about 0.6 points, while sampling error is 1.65.
Experiment 30 documented this trap and it recurred immediately.

### The pre-registered validation kills it

Rather than sweeping caps 4, 5, 7 and 8 to sharpen a peak — which would be
selecting harder on a span already seen 72 times — cap 6 was taken to **2025**,
out of sample, with cap 3 run alongside as a control. Registered before looking:
cap 6 must beat cap 3 in the same direction by roughly +2 points.

| 2025 cell | trades | barrier n | WR | edge | **z** | gross | net |
|---|---|---|---|---|---|---|---|
| cap 3 | 195 | 180 | 23.89 | **−9.29** | −2.92 | −$33,222 | −$45,214 |
| cap 6 | 234 | 213 | 22.54 | **−8.87** | **−3.10** | −$35,862 | −$49,751 |

Both land near −9 and cap 6 is worse in dollars. The training-span +2.24 does not
reproduce. **The cap is not a lever**, and selecting the best of a three-cell
curve produced exactly the kind of number this harness exists to catch.

### The second significant result in the program, and it is negative again

Cap 6 on 2025 reaches **z −3.10**, clearing the |z| > 3 threshold. The only other
result ever to clear it was experiment 29's −5.07 for dropping the OTE gate.

**Every statistically significant number this program has produced is negative.**
Two observations at |z| > 3, both worse than random, against 72 configurations
that otherwise cannot be distinguished from a coin flip.

Do not over-read it. 2025 is one year, it has been seen diagnostically before,
and a −9 point edge on 180 to 213 barrier trades could still be regime rather
than mechanism — 2025 differs sharply from the 2021-24 training span, where the
same configuration measured −0.22. But it is the second time the strategy has
been caught doing something worse than nothing, and the first time on data it
was not fitted to.

### What is now established

1. **The concurrency cap is not a lever.** A +2.24 training-span edge reversed to
   −8.87 out of sample.
2. **The rejection funnel counts bar-level rejections**, so it overstates how
   many trades a loosened gate would add.
3. **72 configurations.** The 2026 holdout remains unopened.

---

## Experiment 31 — The exit is not the problem either (July 2026)

One cell, 20.4 min. `TRADE_MANAGEMENT_ENABLED` had been `False` for all 68
configurations and appeared **zero times** in `logs/experiments.jsonl`. It was
also bound at import time in `trading/positions.py`, so it was never sweepable —
the exact trap the harness notes warn about. Now routed through `params.get()`.

### Why it needed a different test statistic

Partial closes and trailing stops change the payoff functional, so the barrier
win rate, `_geometry` and every paired random-direction null in this repo stop
applying: there is no single stop/target pair left to score. The question is
instead whether a managed exit beats an unmanaged one **on the same entry**, so
the statistic is the per-trade paired delta in net R with a bootstrap interval.
Registered before the run: `mean(d) > +0.03R` with the interval clear of zero is
a real result; 0 to +0.01R is noise.

### It is neutral

| | unmanaged | managed |
|---|---|---|
| trades | 807 | 922 |
| gross | +$5,030 | +$14,693 |
| costs | $57,144 | $67,804 |
| net | −$52,113 | −$53,599 |
| mean R per trade | −0.1044 | −0.0894 |

Paired on 764 entries with identical bar and direction:

| statistic | value |
|---|---|
| mean delta | **+0.0114 R** |
| 95% bootstrap | **[−0.0419, +0.0632]** |
| median delta | 0.0000 R |
| paired t | +0.42 |
| improved / worsened / unchanged | 14.9% / 11.4% / **73.7%** |

**Three-quarters of trades are untouched**, because management only engages on
the minority that reach 1R — which is what experiment 21 already implied with a
median MFE of 0.70R against a 1.59R target and only 24.5% of trades ever
reaching target. A 1R partial harvests a minority event and clips the trades
that were the only source of positive payoff.

The framing that closes the question: mean R is **−0.1044**, so break-even needs
about **+0.10R**. Trade management supplies **+0.011R ± 0.05**, roughly a tenth
of the gap, with an interval that contains zero.

### Two predictions were wrong, and one cost model was

Both this author and Codex pre-registered that management would make results
*worse*. It came out marginally positive per trade. Both were wrong in sign and
both were inside noise, which is the honest description.

The reasoning that produced the wrong prediction is worth recording. The claim
was that a partial close "adds a fill, so adds cost". It does not: total closed
quantity is 100% either way, spread and slippage are charged on quantity filled,
and commission is per contract rather than per ticket. There is no incremental
market cost to splitting an exit in this model. Codex caught that before the run
rather than after.

Costs did rise, from $57,144 to $67,804, but through **more trades** (922 against
807), not more expensive ones — cost per trade barely moved, $70.81 to $73.54.

### Displacement, for the third time

158 entries exist only in the managed run and 43 only in the unmanaged one,
because a managed position releases its concurrency slot sooner. The
three-position cap has now shaped three separate results: it crowded out FVG+OB
overlaps in experiment 29, it bounds trade count at every timeframe in
experiment 30, and it admits 158 extra trades here.

**That makes the cap itself the next thing to test.** It has never been varied.

### What is now established

1. **The exit is not the problem.** Changing the exit rule moves expectancy by
   +0.011R against a ~0.10R gap, with a bootstrap interval containing zero.
2. **The "maybe the exit is the problem" objection is closed** without spending
   the holdout or changing instrument.
3. **69 configurations.**

---

## Experiment 30 — Costs fall with the timeframe and it changes nothing (July 2026)

Two cells, 19 min. The `timeframes` sweep had never actually been run — no `tf:`
labels exist in `logs/experiments.jsonl` — and it only covered 5min and 15min.
30-minute and 1-hour entries had never been tested at all.

### The question, framed as Codex insisted rather than as first proposed

The obvious framing was a cost test: cost drag is `1.02 / stop_points`, the
binding constraint at 11% of R, and a coarser timeframe gives structurally wider
stops. Experiment 27 had already shown that widening the stop on the *same* 15m
entries lowers the bar without creating edge, but that broke the relationship
between the stop and the structure that produced the setup. A coarser timeframe
does not.

Codex rejected the framing anyway, and was right to. Costs are the economic
reason the test could matter; they are not the statistical hypothesis. The only
live claim is structural — **coarser bars may define a different signal
population with different information content** — and lower costs are necessary
but not sufficient. Two outcomes were registered:

- **costs only** — edge stays near zero, net R becomes less negative because
  cost/R falls, and the bar is still missed. Not a tradable result.
- **scale creates edge** — edge rises materially above zero, not merely above
  the lowered bar, and net turns positive.

### It is the first one

Resolver agreement first, because none of the rest means anything without it.
The engine reads a fill from the entry candle's high and low while every null is
resolved on 1-minute data, so the coarser the bar the more room for the two to
disagree — the exact failure that cost experiment 27 a conclusion:

| cell | agree | disagree |
|---|---|---|
| 15m | 807 | **0** |
| 30m | 305 | **0** |
| 1h | 89 | **0** |

One ruler at every timeframe. Then the result:

| cell | trades | barrier n | median stop | WR | **edge** | sampling se | **z** | econ bar | stat hurdle | gross |
|---|---|---|---|---|---|---|---|---|---|---|
| 15m | 807 | 729 | 9.36 | 33.33 | −0.22 | 1.75 | **−0.13** | 4.24 | 5.24 | +$5,030 |
| 30m | 305 | 262 | 12.92 | 32.06 | −2.07 | 2.88 | **−0.72** | 3.07 | 8.65 | −$5,052 |
| 1h | 89 | 72 | 14.21 | 34.72 | **+3.73** | 5.61 | **+0.66** | 2.70 | 16.83 | −$4,712 |

**The cost mechanism worked exactly as predicted and bought nothing.** Stops
widened, cost share fell from 10.9% of R to 7.2%, and the break-even bar fell
from +4.24 to +2.70. Gross went the other way, +$5,030 to −$4,712. A cheaper bar
is worth nothing when there is no edge to protect.

The lever is also weaker than it looks. ATR scales with roughly the square root
of time, so a four-times coarser timeframe bought only 1.5 times the stop.

### The 1h cell looks like a winner and is not

Its +3.73 clears its own economic bar of +2.70, and 100% of the thirty seeds are
positive. Neither fact means what it appears to.

**`P(edge > 0) = 100%` is across seeds, and seeds measure the wrong thing.** The
spread across seeds is null-estimation noise, about 0.6 points. The uncertainty
that matters is sampling error on the strategy's own 72 barrier trades, which is
**5.6 points**. The interval on +3.73 is roughly ±11, and z is +0.66.

This is the trap the pre-registration named in advance, in Codex's words before
the run: *a true +2 or +3 point edge could be economically interesting and still
look like noise.* Reporting the cell as a hit would have been the single easiest
mistake available in this whole program.

### The two hurdles move in opposite directions

This is the general lesson, and it closes the timeframe axis rather than one
cell of it.

| cell | economic bar | statistical hurdle | binding |
|---|---|---|---|
| 15m | 4.24 | 5.24 | statistical |
| 30m | 3.07 | 8.65 | statistical |
| 1h | 2.70 | 16.83 | statistical |

Coarsening the timeframe lowers the economic bar and raises the statistical
hurdle faster, because trade count falls with it. At 1h, three standard errors
is +16.8 win-rate points — an effect size nothing in this program has ever
approached. **The statistical hurdle binds at every timeframe, and coarsening
makes the problem worse.** There is no timeframe on this instrument at which a
marginal edge could be both real and detectable within the available history.

### Two caveats on comparability

Neither cell is a clean one-variable change from the 15m baseline.

**1h collapses the entry and setup timeframes into one bar series**, since
`setup` is already 1H, so the confluence mechanics change rather than only the
entry scale. And `get_windowed_data()` allocates lookback by entry-bar count, so
15m, 30m and 1h see roughly 10, 21 and 42 trading days of history and therefore
different detector populations. Both are properties of the design, not faults,
but they mean these rows are directional evidence rather than controlled
comparisons.

### What is now established

1. **Costs were never the only problem.** They fell as predicted and the result
   did not improve, which is the "costs only" branch registered before the run.
2. **The timeframe axis is closed**, on power rather than on any single result.
3. **68 configurations.** Nothing has cleared its bar at any scale.

---

## Experiment 29 — The OTE gate is the only thing holding the entry up (July 2026)

One pre-registered cell, 20.5 min. The search on 15-minute ES stops here.

### The published explanation was wrong

Experiment 26 attributed a −2.0 point penalty to "a retracement entry into a
fair value gap: entry against immediate momentum", and the next test was to drop
the retracement and enter at market instead.

**The code never waited.** `_find_fvg_ob_overlap` and `_find_fvg_entry` both
`return current_price`. There is no limit order resting in the zone and nothing
waits for price to come back. The strategy has always entered at market on the
signal bar; the zone qualifies the setup and anchors the stop, nothing more. The
measurement stood, the explanation for it did not.

Codex also took the −2.0 apart. It came from an *unpaired* null, so it absorbs
bar location, volatility regime, hour clustering, censoring — real entries are
censored 5.8% against 15.8% for uniform sampling — and setup-conditioned
geometry, with entry timing only the last of those. It is a diagnostic smell,
not a measured defect, and not a quantity to go and fix.

That left one honest question: do standalone FVG entries carry edge without the
OTE gate? `entry_timing` in `backtest/rules.py` now selects it.

### They carry a large negative one

Same bias, same geometry, same span, same 30-seed paired null:

| cell | trades | barrier n | WR | **edge** | sd | P(edge>0) | gross | net |
|---|---|---|---|---|---|---|---|---|
| `retracement` (exp 28) | 807 | 729 | 33.33 | **−0.22** | 0.72 | 37% | +$5,030 | −$52,113 |
| `signal_bar` | 787 | 745 | **20.40** | **−5.07** | 0.67 | **0%** | **−$25,598** | −$87,611 |

Sampling error on 745 barrier trades is 1.6 points, so −5.07 is **z ≈ −3.2**.
After 65-plus configurations that produced nothing distinguishable from zero,
the first result to clear |z| > 3 is an anti-edge.

### The mechanism is displacement, not dilution

The setup mix does not simply gain standalone FVGs, it loses the overlaps:

| setup type | retracement | signal_bar |
|---|---|---|
| FVG+OB overlap | 663 | **106** |
| FVG+OTE | 144 | 26 |
| Fair Value Gap | 0 | **655** |

The entry waterfall still tries FVG+OB overlap first, so the overlaps were not
out-competed on quality. They were crowded out by the three-position concurrency
cap: standalone FVGs fire far more often, take the slots, and the better setup
finds no room when it arrives. Loosening a filter did not add marginal trades to
the existing book. It replaced the book.

That also explains the cost line. Cost per trade rises from $70.81 to $78.80 and
gross turns negative, so costs are no longer eating a small edge — there is no
gross edge left to eat.

### Read what this does and does not say

It does **not** say the OTE gate has edge. Experiment 26 measured FVG+OTE at
+0.4 points on 142 barrier trades, which is nothing. What it says is that the
gate is doing real work as a *filter*: the population it excludes is
significantly worse than random, so removing it makes the strategy worse than
the coin flip it was already indistinguishable from.

### The search stops here

The stopping rule was registered before the run, on Codex's argument: near zero,
negative, or merely +1 point means stop parameter search on 15-minute ES. It
returned −5.07 at P(edge > 0) = 0%.

Every cheap question from experiment 26 is now closed. Across 66 configurations
nothing positive has ever been measured, the one figure that looked positive was
one seed above a mean inside noise, and the only significant result is negative.
What remains is not a sweep: a different instrument, a different horizon, or a
different data source such as order flow.

---

## Experiment 28 — The only positive component in the program was a bug (July 2026)

Runtime: 20.5 min to re-baseline, seconds for the rest. One code change, ten new
tests, five predictions registered before the run and three red flags.

### The question

Experiment 27 found two faults in the day-trade cutoff at `engine.py:307`. The
close fired only on a bar whose ET hour was 16, so on holidays and half-days
with no such bar the position was carried for days; and nothing stopped an entry
being taken during that hour. Fixing both and re-running experiment 26's cell
says what the strategy looks like without them.

### The fix

The close now fires on the last bar at or before 16:00 ET on the bar's own CME
session day, which works whether or not the cutoff bar traded. Entries at or
after the cutoff are refused.

Codex caught a bug in the fix before it was written. The obvious rule — close
when the next bar belongs to a different session day — lands an hour late on
every ordinary weekday, because after 17:00 ET the next bar is the 18:00 evening
open and that already belongs to the next session day. The rule has to be
anchored on the cutoff, not on the session boundary.

Reading the next bar's timestamp to find the last one before the cutoff is not
look-ahead: no price or volume is taken from it, and it stands in for the
session calendar that live trading gets from a clock.

### Every prediction held

| registered before the run | before | after | |
|---|---|---|---|
| gross falls toward break-even | +$10,717.50 | **+$5,030.50** | pass |
| trades drop by roughly 31 | 841 | **807** | pass |
| no entry in the 16:00 ET hour | 31 | **0** | pass |
| no trade spans a session day | 38 | **0** | pass |
| longest hold becomes intraday | 119.2 h | **21.8 h** | pass |

The remaining 21.8-hour hold is one session, not two: an entry on the 18:15 ET
evening open held to the following 16:00 cutoff is 21.75 hours inside a single
CME trading day. Cross-session holds are zero.

All three red flags stayed down. Session-end gross did not rise ($29,900 →
$29,712). No exit landed at 17:00 ET. Net got **worse**, −$49,142.50 →
−$52,113.25, which is what fixing a rule that was handing out free profit should
do.

### The two resolvers now agree exactly

Experiment 27's finding was that the engine and `Intrabar.first_touch` resolved
the same trade differently on 40 of 841 trades, so the strategy and its
benchmark were measured with different rulers. On the fixed run:

| engine | first_touch | n |
|---|---|---|
| SL_HIT | SL_HIT | 486 |
| TP_HIT | TP_HIT | 243 |
| SESSION_END | none | 78 |

**Zero disagreements out of 807.** `nullmodel.session_end()` needed no change
after all: its calendar-day rule only diverged for entries after 16:00 ET, and
those no longer exist. Every edge-against-null figure in this program is now
measured on one ruler.

### The +1.2 direction component does not survive

Experiment 26 recorded a +1.2 win-rate-point direction edge and called it the
first positive component measured anywhere in the program.

A single paired null is one draw. At 6000 draws its win rate carries about 0.7
points of noise, which is most of the effect being argued about, so the first
version of this entry drew a conclusion from one seed and could not support it.
Thirty seeds on each baseline, same geometry, same cutoff:

| baseline | barrier n | strategy WR | null mean | **edge** | sd | range | P(edge > 0) |
|---|---|---|---|---|---|---|---|
| pre-fix | 764 | 34.16 | 33.55 | **+0.61** | 0.66 | −0.9 to +1.7 | 80% |
| post-fix | 729 | 33.33 | 33.55 | **−0.22** | 0.72 | −1.6 to +1.3 | 37% |

Two things fall straight out of that.

**The null does not move.** 33.55 on both baselines, because the null was always
resolved by `Intrabar.first_touch`, which was never the broken component. The
whole change is on the strategy side: its win rate fell 0.83 points, from 261
winners in 764 to 243 in 729, and the edge fell by the same 0.83. That is the
arithmetic of the holiday carries — 14 of the 24 were TP hits a correctly-closed
position never reaches.

**The published +1.2 sits inside the pre-fix seed range.** It was a high draw
from a distribution centred on +0.61, not a separate measurement. So the honest
statement is narrower than "the +1.2 was a bug":

- Under a matched paired null the pre-fix edge is **+0.61 ± 0.66**, not +1.2.
  The published figure came from one favourable seed.
- Fixing the cutoff moves the same measurement to **−0.22 ± 0.72**, and that
  −0.83 shift is attributable to the fix, because the null is unchanged.
- Neither figure is distinguishable from zero, and the bar is +3.5.

What is established is therefore that **no positive direction edge survives**,
and that the number previously treated as positive evidence was one seed above a
mean that was already inside noise. It is not established that direction skill
is negative.

### The stop-width result survives on clean data

Experiment 27's conclusion re-run against the fixed trades, target held at its
original price:

| stop | barrier n | WR | paired null | edge | z | bar | mean net R |
|---|---|---|---|---|---|---|---|
| actual 9.4 | 729 | 33.33 | 34.27 | −0.9 | −0.53 | 4.24 | −0.162 |
| 15 | 689 | 45.43 | 46.04 | −0.6 | −0.32 | 3.14 | −0.082 |
| 20 | 645 | 54.73 | 53.93 | +0.8 | 0.41 | 2.69 | −0.046 |
| 30 | 593 | 64.25 | 65.10 | −0.9 | −0.43 | 2.10 | −0.056 |
| 40 | 541 | 73.01 | 74.56 | −1.5 | −0.83 | 1.72 | −0.046 |
| 60 | 459 | 87.58 | 88.22 | −0.6 | −0.42 | 1.28 | −0.034 |

Same flat noisy line, max |z| 0.83, mean net R negative at every width. The
+3.5 selection artifact that appeared at a 60-point stop in the secondary table
of experiment 27 is now +1.1, which is what a best-of-twelve artifact does when
the data underneath it moves.

### Two things this entry does not establish

Recorded because the first draft claimed both, and a Codex review of the writeup
was right to reject them.

**That the fix caused a sign flip.** The pre-fix trades rescored with the same
script already averaged +0.61, not +1.2. The fix moved it to −0.22. Both sit
inside noise, so what moved is a mean, not a sign.

**That the terminal bar is handled correctly.** `session_cutoff_masks` marks the
last bar of any series as a session close, so a run that ends mid-session labels
its final exit `SESSION_END` rather than something like `BACKTEST_END`. It is
cosmetic here — one trade at the end of the span — but it is wrong, and the
test at `tests/test_session_cutoff.py` currently locks the behaviour in.

One test gap is also open. The ten isolation tests would all still pass if a
future refactor moved the force-close below the `step_bars` skip in
`_run_backtest_inner`, at which point `step_bars > 1` could skip a close bar and
carry a position again. Nothing in `tests/` calls `run_backtest` at all, so the
loop's ordering has no coverage.

### What is now established

1. **No positive direction edge survives.** −0.22 ± 0.72 over thirty seeds
   against a bar of +3.5.
2. **The strategy and its benchmark now resolve identically** on all 807 trades,
   so future edge figures are comparisons of skill rather than of rulers.
3. **Costs are 11.4 times gross.** $57,143.75 against +$5,030.50.

The two open questions from experiment 26 are both closed. What remains needs a
different instrument, a different data source such as order flow, or accepting
that 15-minute ES is efficient at this horizon.

---

## Experiment 27 — A wider stop does not pay, and two session-end faults surface (July 2026)

Configurations tried to date: **65**, plus twelve offline re-resolutions of
experiment 26's own trades, which are twelve correlated looks and are priced as
one family below. Runtime: 22 min to regenerate the trades, seconds to rescore.

### The question

Experiment 26 measured a +1.2 win-rate-point direction component at z 0.68. The
break-even bar falls as `1.02 / stop_points`, from about +3.5 points at the
observed 9.2-point stop to about +1.2 at 30. So the whole question is the shape
of edge against stop width, and re-resolving the stored trades answers it
without changing the population.

Pre-registered before looking, after a Codex challenge that changed three things:

- **Two counterfactuals, not one.** Holding each trade's target *multiple*
  constant while widening the stop pushes the target price out too, so it tests
  "does the signal work at the same shape, larger scale". The engine picks
  targets from liquidity, and that price does not move because the stop moved.
  The primary reading is therefore **fixed target price, stop widened alone**.
- **Twelve looks are one family.** Requiring z > 3 per look is too loose on top
  of 65 prior configurations. The threshold was set at max-z ≥ 3.4, and a
  result had to show a plausible rise-plateau-fade shape rather than one point
  clearing the bar.
- **Censoring is reported, not assumed harmless.** The paired null shares the
  16:00 cutoff but not necessarily the resolution *rate*: if correctly-directed
  trades resolve at a different rate from wrongly-directed ones, conditioning on
  resolution biases the direction edge itself. Mean net R over every trade,
  closing the unresolved at the cutoff, avoids that conditioning.

### The regeneration reproduces experiment 26 exactly

841 trades, gross +$10,717.50, costs $59,860, 503 SL / 261 TP / 77 session-end,
non-barrier +$25,492.50. Every headline figure matches. That is the fourth
independent determinism check on this harness.

### A wider stop does not pay

Primary — target held at its original price, stop widened alone:

| stop | barrier n | censored | WR | paired null | edge | z | bar | mean net R | t |
|---|---|---|---|---|---|---|---|---|---|
| actual 9.5 | 760 | 9.6% | 33.03 | 33.52 | **−0.5** | −0.29 | 4.21 | −0.177 | −3.60 |
| 15 | 720 | 14.4% | 44.86 | 45.53 | **−0.7** | −0.36 | 3.14 | −0.094 | −2.38 |
| 20 | 675 | 19.7% | 54.37 | 54.35 | **0.0** | 0.01 | 2.68 | −0.053 | −1.60 |
| 30 | 612 | 27.2% | 64.71 | 65.43 | **−0.7** | −0.38 | 2.09 | −0.053 | −2.10 |
| 40 | 560 | 33.4% | 73.21 | 74.58 | **−1.4** | −0.74 | 1.72 | −0.045 | −2.13 |
| 60 | 476 | 43.4% | 87.61 | 87.55 | **+0.1** | 0.04 | 1.28 | −0.034 | −2.24 |

Secondary — target multiple held, so the target widens with the stop:

| stop | barrier n | censored | WR | paired null | edge | z | bar | mean net R | t |
|---|---|---|---|---|---|---|---|---|---|
| actual 9.5 | 760 | 9.6% | 33.03 | 33.52 | −0.5 | −0.29 | 4.21 | −0.177 | −3.60 |
| 15 | 659 | 21.6% | 32.02 | 31.44 | +0.6 | 0.32 | 2.43 | −0.106 | −2.41 |
| 20 | 542 | 35.6% | 31.00 | 30.30 | +0.7 | 0.35 | 1.82 | −0.073 | −1.86 |
| 30 | 377 | 55.2% | 27.59 | 27.40 | +0.2 | 0.08 | 1.21 | −0.069 | −2.15 |
| 40 | 246 | 70.7% | 23.17 | 24.54 | −1.4 | −0.50 | 0.91 | −0.062 | −2.30 |
| 60 | 91 | 89.2% | 19.78 | 16.24 | **+3.5** | 0.92 | 0.61 | −0.042 | −2.15 |

**The primary curve wobbles around zero.** Edge runs −0.5, −0.7, 0.0, −0.7,
−1.4, +0.1 against a bar that falls from 4.21 to 1.28, and never approaches it.
Max |z| is 0.74 against a threshold of 3.4. There is no rise, no plateau and no
fade — it is the flat noisy line predicted under no real edge.

The +3.5 at a 60-point stop in the secondary table is the selection artifact the
pre-registration named in advance: 91 barrier trades out of 841, 89% censored,
z 0.92. Best of twelve correlated looks, and it fails the family threshold by a
factor of nearly four.

**Mean net R is negative at every stop in both tables**, from −0.177 to −0.034,
at t −1.6 to −3.6. That figure uses every trade and closes the unresolved at the
cutoff, so it does not condition on resolution at all. A wider stop shrinks the
loss per R because cost drag falls as `1.02 / stop`; it never turns it positive.

**Backlog item 1 is dead.** The direction component does not grow with stop
width, so the one positive number measured in this program has no economic value
at any geometry.

### The validation row failed, and that mattered more

The rescore's actual-stop row should have reproduced experiment 26's barrier
figures. It did not: 33.03% on 760 barrier trades against the engine's 34.16% on
764. Same trades, same stops, same targets. The strategy win rate comes from the
engine while every null in this program is resolved by `Intrabar.first_touch`,
so a disagreement between those two resolvers is a difference of rulers, not of
skill — and at 2.1% of trades on the figure that drives the win rate, it is
larger than the effect being measured.

Resolving all 841 trades both ways gives the disagreement directly:

| engine | first_touch | n |
|---|---|---|
| SL_HIT | SL_HIT | 495 |
| TP_HIT | TP_HIT | 247 |
| SESSION_END | none | 59 |
| SESSION_END | SL_HIT | 14 |
| TP_HIT | none | 14 |
| SL_HIT | none | 8 |
| SESSION_END | TP_HIT | 4 |

Forty of the 841 are outright class disagreements, **4.8%**. `SESSION_END → none`
is agreement rather than a third class: both say no barrier was reached before
the cutoff. Of the forty, eighteen change the win/loss verdict itself, which is
2.1% and is what moves the barrier win rate.

Two separate faults, both in the session-end close at `engine.py:307`.

**A. The engine takes entries during the 16:00 ET hour.** The force-close runs
before the entry logic on the same bar, and nothing stops an entry at the cutoff
hour. 31 trades entered there, spread across all four 15-minute bars (7, 6, 7,
11). Nineteen of them are the pure case — closed `SESSION_END` on the very next
bar, $974 of costs for a 15-minute hold, net −$911. The remaining twelve ran to
a barrier, 9 stops and 2 targets, and drag the whole group to $1,691 of costs
and net −$5,719. The clean statement of the fault is the nineteen; the group
figure describes every entry in that hour, which is a larger and looser claim.

**B. The engine holds through market holidays.** The close fires only on a bar
whose ET hour is 16. Databento omits minutes with no trade, and on a holiday or
half-day session no such bar exists, so the position rides into later sessions.
**37 of the 894 weekday sessions in the training span — 4.1% — have no 16:00 ET
bar at all**: every US market holiday and half-day, Thanksgiving and the Friday
after, Independence Day, Labor Day, Good Friday 2023, Juneteenth 2024, Christmas
Eve. On each of those the close cannot fire. 24 trades were caught by it, median
hold 20.6 hours, longest 119.2 — entered 2023-06-30, closed 2023-07-05, straight
through Independence Day. The rest cluster on Thanksgiving 2022 and 2023.

Fault B is the one that matters. Those 24 trades returned **+$9,958.50 gross**
against the whole run's **+$10,717.50 gross**, and 14 of the 24 are TP hits.
Nearly all of the gross profit in the run came from trades that broke the
documented day-trade rule by running for days. It does not rescue the strategy —
the run still lost 49.1% net — but any future configuration that looked
gross-positive could have been reading this.

The two sets overlap by one trade, so 54 of the 841 are affected.

Both faults descend from the audit fix recorded at the top of this file, which
replaced an unbounded `hour >= 16` with a bounded check. Bounding it was right.
Anchoring it to the existence of a bar in that hour was not.

### What this does not change

The stop-width conclusion stands. Strategy and paired null share one resolver
and one cutoff in the rescore, so the edge comparison is internally consistent
even though the absolute win rates differ from the engine's.

### What is now established

1. **A wider stop does not pay.** Edge against a matched paired null is flat in
   stop width at every geometry tested, and mean net R is negative at all of
   them. The +1.2 direction component has no economic value.
2. **The engine and the null model resolve the same trade differently** on 4.8%
   of trades, 2.1% of them changing the win/loss verdict, for two reasons that
   are now named and sized.
3. **Twenty-four trades broke the day-trade rule** and supplied +$9,958.50 gross
   against the whole run's +$10,717.50.

Next: fix both faults and re-baseline. Fault A wants an entry guard at the
cutoff hour; fault B wants the close driven by the session calendar rather than
by a bar happening to exist. Neither has a test — `test_costs.py:75` checks what
a session-end exit costs and `test_nullmodel.py:22` checks the `session_end()`
helper, but nothing checks when the engine actually closes, which is why both
survived the audit. Experiment 26's baseline has to be re-run afterwards,
because 54 of its 841 trades are affected.

### What Codex found in this writeup

The review before implementation shaped the design. The review after it caught
three errors in the numbers above, all corrected here: fault A was described as
"opens on the 16:00 bar and closes on the next one" when the measured 31 are
every entry in that hour and only 19 are next-bar stubs; the affected union was
given as 55 when the two sets overlap by one trade; and the resolver
disagreement was given as 3.5% when the matrix supports 4.8%, or 2.1% on the
verdict-changing subset. It also supplied fault B's gross, which replaces a
net-against-gross comparison that was not apples to apples. Claim 1, the
stop-width result, it checked clean.

---

## Experiment 26 — No concept carries edge, and the search is closed (July 2026)

Configurations tried to date: **65**. Runtime: 21.8 min for the decomposition,
seconds for the two measurements that follow it.

### The question

Experiment 25 measured total edge at zero over 878 barrier trades. That leaves two
readings: every concept is noise, or some are positive and some negative and they
cancel. The confluence score adds them up and has no predictive slope, which fits
cancellation. The entry waterfall records which concept fired, so one run decides
it. Pre-registered before looking: a concept is worth pursuing only at z > 3 with
200+ barrier trades.

### Both concepts sit exactly on their own null

Full training span, 15m, best bias rule, each setup type against its own matched
null:

| setup type | trades | barrier n | WR | matched null | edge | z | net P&L |
|---|---|---|---|---|---|---|---|
| FVG+OB overlap | 683 | **622** | 35.0% | 34.83% | **+0.2** | **+0.11** | −$46,250 |
| FVG+OTE | 158 | 142 | 30.3% | 29.85% | **+0.4** | **+0.11** | −$2,892 |
| *whole run* | 841 | 764 | 34.2% | 34.18% | **−0.0** | **−0.01** | −49.1% |

**Cancellation is false.** FVG+OB overlap carries three times the pre-registered
sample floor and returns +0.2 points where +3.5 is needed. The 95% interval on
that edge is [−3.5, +3.9], so break-even sits at its extreme upper edge.

The whole result is two recorded numbers: **gross +$10,717 against costs of
$59,860.** Max drawdown 62%.

### The one asymmetry in the run is survivorship, not edge

`nonbarrier_pnl` is **+$25,492 over 77 trades**, so the forced 16:00 closes were
the only gross-positive component. That suggests a time exit might beat a target
exit, which would be a genuinely different rule. It is not: a trade still open at
16:00 is one that has not been stopped, so conditioning on survival selects
winners mechanically.

Measured directly on random entries — stop only, no target, exit at 16:00, over
the training span:

| stop | direction | n | stopped | mean R gross | mean R net | t |
|---|---|---|---|---|---|---|
| 9.2 pt | LONG | 5995 | 69.9% | +0.0397 | −0.0707 | −2.59 |
| 9.2 pt | SHORT | 5995 | 71.8% | −0.0281 | −0.1385 | −4.84 |
| 20 pt | RANDOM | 5995 | 48.1% | −0.0091 | −0.0601 | −3.40 |
| 40 pt | RANDOM | 5995 | 22.5% | −0.0029 | −0.0284 | −2.61 |

Gross expectancy is nil at every stop width. The best figure, +0.04R on the long
side at a tight stop, is the 2021-24 equity drift, and it does not survive 0.11R
of costs. Net is significantly negative everywhere.

This also confirms the cost model arithmetic independently: gross minus net is
0.1104R at a 9.24-point stop against a predicted 1.02/9.24 = 0.1104, and 0.0255R
at 40 points against 1.02/40 = 0.0255.

### The paired null splits it into timing and direction

The cell was run twice — once before the paired null existed and once after — and
both produced identical stats (841 trades, WR 35.9%, PF 0.85, −49.14%), which is a
free determinism check. Both rows are kept. The second carries the decomposition:

| null | what it randomises | rate | strategy edge | z |
|---|---|---|---|---|
| unpaired | a random bar **and** direction | 34.99% | −0.8 | −0.48 |
| **paired** | direction only, at the strategy's **own** bars | **33.00%** | **+1.2** | **+0.68** |
| analytic formula | — | 35.78% | — | — |

A coin flip at the moments this strategy chooses scores **2.0 points worse** than a
coin flip at random moments. So the result decomposes:

- **Timing: −2.0 points.** The chosen moments are intrinsically harder — the stop
  is hit first more often *whichever way the trade is taken*. That is what a
  retracement entry into a fair value gap does: it enters against immediate
  momentum, with a stop sized from an ATR that does not know it.
- **Direction: +1.2 points.** The bias rule beats a coin flip at those same
  moments. This is the first positive component measured anywhere in the program.

Read it carefully before acting on it. z is 0.68, the interval on +1.2 is ±3.4 and
contains zero, and the bar is +3.5. Even a perfect fix to the timing leaves +1.2
against +3.5 at a 10-point stop — though the bar falls to +1.2 at a 30-point stop,
which is exactly break-even and nothing more.

What it does do is convert "nothing works" into one concrete testable claim: **the
entry trigger subtracts about two points and the bias rule adds about one.** The
test is to keep the bias and drop the retracement requirement — enter at market on
the signal bar — and see whether timing goes neutral. That is one cell, about 22
minutes, and it is the first time the evidence has pointed at a specific change
rather than at another sweep.

### What is now established

1. **The entry has no net edge.** z +0.11 per concept at n=622 and n=142, z −0.01
   to −0.48 overall at n=764, scored against random entries at matched geometry
   under matched censoring. The decomposition above shows this is a −2.0 timing
   component partly offset by a +1.2 direction component, neither significant.
2. **Barrier exits have no edge**, by the same measurement.
3. **A time exit has no edge either**, gross or net, at any stop width.
4. **Costs are the binding constraint and they are structural.** 1.02 points of
   spread, slippage and commission on a 9.24-point stop is 11% of R, and it is
   independent of position size.
5. **Sixty-five configurations reach the +3.5-point bar nowhere.** Bias rules,
   triggers (levels and CISD), timeframes (15m and 5m), all three strategies,
   direction filters, inversion, and now both entry concepts individually.

Parameter search on this implementation cannot succeed, and that is a measured
statement rather than an impression. What remains needs a decision, not a sweep:
a different instrument, a different data source such as order flow, or accepting
that 15-minute ES is efficient at this horizon.

### Correction to the record

An earlier note in this session recorded the first decomposition run as having
"died with no row and no error", and hardened the diagnostics in response. The run
had not died — it completed normally in 21.8 minutes and I read the log before it
flushed. The hardening is worth keeping on its own merits (an optional diagnostic
should never be able to lose an expensive backtest, and the shared 1-minute view
removes a per-setup-type copy), but it fixed a fault that was never demonstrated.

---

## Experiment 25 — The edge metric was measuring the wrong population (July 2026)

Configurations tried to date: **64**. Runtime: 28 min for the extension, plus
seconds for everything else — the two findings here cost almost no compute
because they came from re-reading stored results, not from running new ones.

### What was tested

Experiment 24 ended with one positive cell: Silver Bullet on 2023 H2 at 5m,
reported at +15.0 points over its benchmark, PF 1.60, +8.0% return. The
pre-registered test was to re-run it on three year-long slices the screen never
saw and require a positive edge in all three, a pooled z above 3, and profit in
more than one regime.

### It failed the test, and then the test itself turned out to be wrong

Out-of-screen, by the metric in force at the time:

| slice | n | win rate | benchmark | edge | PF | return |
|---|---|---|---|---|---|---|
| 2021-08 → 2022-07 | 23 | 47.8% | 28.0 | +19.8 | 1.59 | +5.9% |
| 2022-08 → 2023-06 | 42 | 16.7% | 29.6 | −12.9 | 0.17 | −21.5% |
| 2024 | 58 | 43.1% | 28.2 | +14.9 | 1.03 | +0.9% |

Two of three positive, one catastrophic, combined return −14.7%. That already
failed the pre-registered bar. But the combination was arithmetically odd:
break-even at a 2.2:1 target with 9.7% cost drag needs only about +3 points of
edge, so a pooled +6.3 should have made money and did not.

**Bug 12 — the benchmark and the win rate described different populations.**
`edge_vs_coinflip` subtracted `stop / (stop + target)` from the *overall* win
rate. That formula is the first-passage probability for a random walk between two
absorbing barriers: it describes a trade that ends at its stop or its target and
nothing else. Session-end and circuit-breaker closes end at whatever price is
there. They were counted as wins whenever P&L was positive, and they skew to
small positive scratches — 26 of them across these four runs, an 81% "win rate"
contributing $7.9k, against barrier trades netting −$14.6k.

Restricting the comparison to barrier exits:

| slice | barrier n | TP/SL | barrier WR | edge | *previously* |
|---|---|---|---|---|---|
| 2023 H2 *(selected)* | 20 | 8/12 | 40.0% | +11.0 | *+15.0* |
| 2021-08 | 16 | 5/11 | 31.3% | +3.3 | *+19.8* |
| 2022-08 | 36 | 3/33 | 8.3% | −21.3 | *−12.9* |
| 2024 | 50 | 17/33 | 34.0% | +5.8 | *+14.9* |

Pooled out-of-screen: 102 barrier trades, 24.5% against a 28.7% benchmark —
**−4.2 points, z −0.93.** The positive result was the metric, not the strategy.

Every run had stored per-exit-reason counts all along, so `load_store` now
derives the corrected figures for all 64 historical cells rather than re-running
them. Recomputing a published number from data already on disk is a correction;
editing the stored numbers would not be, so the backfill derives and never
mutates. Of 45 rankable cells, **2 have a positive barrier edge and none reach
z 3; the highest is 0.91.** The positive cells are the small samples.

### Bug 13 — partial closes took the raw target price

`_check_position_fill_managed` passed `target_1r` straight to `_partial_close`
while every other exit went through `_apply_slippage`. Latent, because trade
management is off by default, but it would have understated costs on exactly the
configuration meant to reduce drawdown.

### The benchmark was biased in the other direction too

`stop / (stop + target)` assumes **unlimited time**. Positions are force-closed
at 16:00 ET, and because the target sits farther away than the stop it needs more
time, so the cutoff removes target-hits more often than stop-hits. Scoring a
time-censored sample against an uncensored null understates every result — the
mirror image of bug 12.

Rather than patch the formula, `backtest/nullmodel.py` measures the null: random
entry times, random directions, stop and target distances sampled from what the
strategy actually used, resolved through the same 1-minute first-touch logic and
the same cutoff. The only remaining difference between null and strategy is which
moment and which direction was chosen — the thing under test. It also captures
what no formula does: real ES drift, volatility clustering and the shape of the
session. Six thousand draws take 0.1 seconds, so it now runs on every cell.

Measured overstatement of the analytic formula, and it scales with the target
multiple:

| cell | target mult | analytic | measured null | bias |
|---|---|---|---|---|
| default 15m 2023 | 1.70x | 37.10% | 36.98% | −0.1 |
| SB 2022-08 | 2.38x | 29.60% | 27.91% | −1.7 |
| SB 2024 | 2.55x | 28.20% | 26.07% | −2.1 |
| SB 2021-08 | 2.57x | 28.00% | 24.95% | −3.1 |
| SB 2023 H2 | 2.45x | 29.00% | 25.64% | −3.4 |

So censoring explains about a quarter of the gap, not all of it. Against the
measured null:

| cell | strategy WR | null WR | edge | z |
|---|---|---|---|---|
| default 15m 2023 | 27.1% | 36.98% | **−9.8** | **−3.41** |
| SB 2023 H2 *(screen)* | 40.0% | 25.64% | +14.4 | +1.47 |
| SB 2021-08 | 31.2% | 24.95% | +6.3 | +0.58 |
| SB 2022-08 | 8.3% | 27.91% | −19.6 | −2.62 |
| SB 2024 | 34.0% | 26.07% | +7.9 | +1.28 |

Pooled out-of-screen: **−2.0 points, z −0.47.**

### What to conclude

1. **Silver Bullet is indistinguishable from random.** The measured null moves
   the pooled out-of-screen figure from −4.2 to −2.0 at z −0.47.
2. **So is the confluence entry, at n≈850 and z≈0.** This is the most
   trustworthy number in the project: the largest samples available, scored
   against random entries at matched geometry under matched censoring. The ICT
   confluence entry neither beats nor loses to a coin flip. It just pays costs.
3. **The bar is +3.5 points of edge** at today's stop width, and the best
   measured is +0.5. No parameter change closes a gap that size, because the gap
   is not in the parameters.
4. **The metric mattered more than any parameter.** Sixty-four configurations
   produced no reliable winner; the one apparent winner was an artefact of
   scoring; and the "worse than random" reading that replaced it was an artefact
   of screening on one year. All three corrections came from re-reading data
   already on disk, at a total compute cost of about six seconds.

### Then the measured null overturned conclusion 2 as well

Re-scoring all 41 historical cells against a matched measured null took six
seconds, and the full-span rows say something the 2023 screen rows cannot:

| config | span | barrier n | edge vs null | z |
|---|---|---|---|---|
| bias:all4_majority | **2021-07 (3.5y)** | **878** | **+0.5** | **+0.33** |
| bias:all4_v3 | 2021-07 | 843 | +0.2 | +0.13 |
| bias:no_pd_plurality | 2021-07 | 798 | 0.0 | +0.03 |
| bias:no_pd_v2 | 2021-07 | 803 | −0.1 | −0.03 |
| bias:struct_liq_v2 | 2021-07 | 567 | −1.1 | −0.55 |
| *the same four* | *2023 only* | *278–354* | *−3.7 to −6.2* | *−1.3 to −2.2* |

**"Significantly worse than random" was a 2023 artefact.** Over the full training
span, at the largest samples in the project, the entries sit exactly on their
null. Across all 41 cells: 3 positive, none above z +2, and the mean
overstatement of the analytic formula is **0.34 points** — not the 1.3 estimated
from the five Silver Bullet cells, because the bias is concentrated where target
multiples are widest.

### Zero edge plus costs explains every loss, with no bug involved

At edge 0 and a 1.90x target the gross expectancy is +0.012R. Costs are ~0.10R.
Net −0.088R per trade over 878 barrier trades is −77R, which compounds to the
observed −48.8%. A coin flip paying a toll.

That makes the profitability bar exact for the first time. Break-even needs
`WR = (1 + cost_share) / (1 + mult)`, so the required edge over a matched null is:

| stop | cost as share of R | required edge (mult 1.9) |
|---|---|---|
| 10 pt *(today)* | 10.2% | **+3.5 pts** |
| 15 pt | 6.8% | +2.3 pts |
| 20 pt | 5.1% | +1.8 pts |
| 30 pt | 3.4% | +1.2 pts |
| 40 pt | 2.6% | +0.9 pts |

Best measured edge is +0.5 at z 0.33. So stop width is a real lever on the
*bar* — 30-point stops would turn −48% into roughly −5% — but at +0.5 edge no
stop width reaches profit. **Nothing here is fixed by a parameter.**

Note this does not resurrect the wide-stop hypothesis that experiment 21
rejected. That test compared MFE measured in R, which mechanically shrinks as the
stop widens, so it could not have detected a cost benefit either way. The correct
question — does edge over a matched null hold up while the required edge falls? —
needed the null to be askable at all.

### Correction to the record

Experiment 24's headline — "the first cell in 59 configurations with positive
edge" — was produced by the broken metric and does not stand. Its bias-sweep
tables, and every `edge_vs_coinflip` figure in experiments 15 to 24, are
inflated by the session-end share; the qualitative conclusions there were all
negative and are unaffected in direction, but the magnitudes are wrong. Rankings
regenerated from `load_store` supersede them.

---

## Experiment 24 — Both ICT strategies were dead code (July 2026)

> **Superseded in part by experiment 25.** The "+15.0 edge, first positive cell"
> headline came from a metric that counted session-end closes as wins against a
> two-barrier benchmark. Corrected, that cell is +11.0 in the screen and −2.0
> pooled across three out-of-screen slices at z −0.47. The bug it fixed (both
> strategies returning no trades) is real and stands.

Configurations tried to date: **56**.

### Bug 10: a key-name mismatch meant neither ICT strategy could ever trade

`strategies` had existed since the harness was built and had never been run. Running
it gave **0 trades from `ict_2022` and 0 from `silver_bullet`** over all of 2023 —
23,564 consecutive declines each. The rejection funnel said only "strategy declined",
so I traced the exit points directly: bias was neutral on **2,065 of 2,065**
kill-zone bars.

The cause is a silent shape mismatch. `common.run_smc_detections` emits its own key
names, and `get_htf_bias` hands those dicts straight to `determine_ict_bias`, which
reads the confluence path's names:

| `bias_factors` reads | strategy path provided |
|---|---|
| `previous_high_low` | `pdhl` |
| `liquidity_zones` | `liquidity` |
| `premium_discount` | **absent entirely** |

Three of the four factors abstained on every bar, so bias was always neutral and
both strategies returned None forever. Nothing failed loudly. Adding the canonical
names alongside the old ones, and computing premium/discount, moved strategy-path
bias from **0.0% to 24.7% directional**.

A regression test now asserts `run_smc_detections` output is consumable by
`bias_factors` and that at least one factor can vote.

### With the fix, one strategy trades and it is still losing

| Cell | Entry TF | n | WR | PF | Return |
|---|---|---:|---:|---:|---:|
| ict_2022 | 15m | 23 | 21.7% | 0.53 | -7.0% |
| ict_2022 | 5m | 42 | 14.3% | 0.46 | -16.1% |
| silver_bullet | 15m | **0** | — | — | — |
| silver_bullet | 5m | **0** | — | — | — |
| default (control) | 15m | 310 | 28.4% | 0.60 | -52.2% |

23 and 42 trades are far too few to read a win rate — below even the 30-trade
ranking floor. What can be said is that selectivity did not produce quality: the
2022 model's win rate is *lower* than the unselective confluence path's.

### Bug 11: Silver Bullet is over-constrained relative to the methodology

Silver Bullet still produced zero at 5m, and the trace shows why: window bounds are
found correctly (spans of 1-12 bars), bias fires, but **the sequence is never found
inside the window** — 220 of 220 in-window directional bars fail there.

The implementation requires the *entire* sweep-then-MSS-then-FVG chain to fall inside
one one-hour window. With `swing_length = 5`, a CHoCH needs a swing to form, be
confirmed, and then be broken — roughly 15+ bars. The window holds 4 bars at 15m and
12 at 5m. So it is not selective, it is arithmetically impossible.

Research describes the actual rule as the *first FVG formed inside the window*,
aligned with HTF bias and an MSS — the FVG is the in-window requirement, not the
whole chain. **The code is stricter than the doctrine it implements**, and that
excess strictness is the difference between a rare setup and no setup.

The fix is well-defined: require only the FVG inside the window and let the sweep and
MSS precede it. Not yet applied.

### Where this leaves the search

Six sweeps, 56 configurations, eleven bugs. The two "concrete ICT strategies" that
the README presents as the sophisticated path turn out to have been non-functional —
one from a dict-shape mismatch, one from an impossible constraint. Neither has ever
produced a testable sample.

That changes the reading of the whole exercise slightly. The negative results so far
are about the **confluence path**, which is genuinely well-tested at this point. The
strategy path has never been tested at all, because it never ran. Fixing Silver
Bullet's constraint and getting both to a readable sample size is the honest next
step before drawing a conclusion about ICT on ES.

---

## Experiment 23 — The 5m execution ladder backfires; the confluence score is noise (July 2026)

Configurations tried to date: **48**.

### ICT's execution ladder, tested and falsified

Every prior run executed on 15m, which is ICT's *array* timeframe. His day-trade
ladder is 1H bias, 15m context, **5m execution**, and his documented way to improve
R:R is to shrink the stop by dropping timeframes while leaving the target alone. The
prediction was that a tighter stop would push favourable excursion measured in R
above target R, breaking the 0.70R ceiling that had held everywhere.

Half-year span (2023 H2) for all three arms so they are comparable; 5m yields more
trades over six months than 15m does over twelve.

| Cell | n | WR | Coin-flip | Edge | z | Stop | Target R | Median MFE | Cost/R | Return | Runtime |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 15m control | 183 | 33.3% | 37.0% | -3.7 | -1.04 | 10.2 | 1.55 | **0.65R** | 10.1% | -35.6% | 3.5 min |
| 5m levels | 460 | 26.7% | 36.5% | -9.8 | -4.37 | 6.2 | 1.60 | **0.52R** | 16.6% | -73.2% | 9.0 min |
| 5m CISD | 972 | 27.6% | 31.9% | -4.3 | -2.88 | 3.7 | 2.22 | **0.55R** | 27.6% | -87.5% | 9.0 min |

**Dropping to 5m made excursion in R terms worse, not better: 0.65R to 0.52-0.55R.**

The mechanism is mechanical and worth stating, because it generalises. A tighter
stop does shrink R — but it also shortens how long the trade survives, and MFE is
measured over the trade's life. The position is terminated before excursion can
accumulate. Losers' MFE falls to 0.24-0.29R: they die almost immediately.

So ICT's "shrink the stop by dropping timeframes" prescription does not transfer to a
mechanised version of this rule set. Meanwhile cost drag rises from 10.1% to 27.6%
of R, because `cost_share_of_R = 1.02 / stop_points` and a 3.7-point stop is brutal.

5m is strictly worse than 15m on every axis measured.

### The confluence score carries no information

Pooling `score_buckets` across all 45 recorded cells — 22,574 trades:

| Confluence score | Trades | Win rate |
|---|---:|---:|
| 60-65 | 1,346 | 34.3% |
| 65-70 | 1,301 | **40.4%** |
| 70-75 | 1,192 | **23.7%** |
| 75-80 | 2,446 | 35.0% |
| 80-100 | 16,289 | 33.1% |

Non-monotonic, and the slope from lowest bucket to highest is **-1.3 points**. The
70-75 band is the worst at 23.7% while 65-70 is the best at 40.4%. That is noise.

Two consequences:

- **The 17-weight confluence system — the centrepiece of the strategy — does not
  rank setups.** `MIN_CONFLUENCE_SCORE` is a trade-count throttle, not a quality
  filter.
- **A confluence-weight sweep is pointless.** Reweighting cannot turn noise into
  signal, so that planned sweep is dropped rather than run. Second hypothesis killed
  by measurement rather than compute.

Also note **72% of all trades score 80 or above** (16,289 of 22,574). With weights
summing to 129 against a threshold of 60, nearly everything passes and most things
saturate the top band, so the scale fails as a ranking device even before asking
whether its factors predict anything.

Caveat: these cells share underlying setups, so 22,574 is not 22,574 independent
observations. The non-monotonicity is stark and consistent regardless.

### Two hypotheses killed without spending compute

Experiment 21 dropped the wide-stop sweep because losers never travel far enough for
a wider stop to rescue them. This experiment drops the confluence-weight sweep for
the same kind of reason. Measuring first and sweeping second has now saved roughly
an hour of runtime and, more importantly, kept two dead ends out of the trial count.

### What is genuinely left

One thing, and it is a different code path rather than another parameter: the two
concrete ICT strategies, `ict_2022` and `silver_bullet`. They require a temporal
sequence — liquidity sweep, then market structure shift, then FVG entry, in causal
order — and they gate on kill zones. That is far more selective than anything tested
so far, and selectivity is the one remaining avenue the evidence supports: fewer,
better trades directly attack a cost drag of 10-28% of R.

The `strategies` sweep has existed since the harness was built and has never been
run.

---

## Experiment 22 — CISD is a better trigger and a worse strategy (July 2026)

Configurations tried to date: **45**. New module `ict/cisd.py`, 15 tests.

### Why CISD

Research flagged FVG and CISD as the only ICT concepts that are **causally clean**.
Order blocks are defined retroactively — "the last down candle before the up move"
reads future data — so any edge they show in a backtest is suspect however
carefully it is written. CISD reads closed candle *bodies* against an opening price
known before the signal bar opened: a run of down candles establishes a reference at
the first candle's open, and delivery has flipped when a later candle closes through
it. Wicks do not count.

The current entry rests on order blocks, so this is the first trigger tested here
that cannot cheat.

### Result

| Cell | n | WR | Coin-flip | Edge | z | Stop | Cost/R | Gross | Return |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| cisd_short_only | 817 | 26.9% | 28.8% | **-1.9** | **-1.20** | 5.2 | 19.7% | -$24.9k | -87.0% |
| cisd_age20 | 798 | 25.4% | 29.6% | -4.2 | -2.60 | 4.6 | 22.2% | -$30.0k | -87.5% |
| cisd_age10 | 815 | 25.8% | 30.1% | -4.3 | -2.68 | 5.2 | 19.7% | -$27.6k | -87.5% |
| cisd_age5 | 768 | 25.7% | 30.5% | -4.8 | -2.89 | 5.3 | 19.4% | -$31.8k | -87.6% |
| levels (control) | 310 | 28.4% | 37.1% | -8.7 | -3.17 | 9.3 | 11.0% | -$29.7k | -52.2% |

**CISD is the better trigger and the worse strategy.** Its edge over benchmark is
-1.9 to -4.8 against the zone finders' -8.7, and `cisd_short_only` at z = -1.20 is
the closest anything has come to its own benchmark. But it fires 2.6x as often (800
trades against 310) on stops half as wide (5 points against 9), so cost drag doubles
to **19.7-22.2% of R** and the return goes from -52% to -87%.

Gross P&L is negative on every arm, so this is not a costs-only story either.

### The invariant that settles it

Median favourable excursion is **0.70 to 0.74R in every single configuration
tested** — both triggers, both directions, all six bias vote rules, normal and
inverted. Target-reach rate sits at 22-24% throughout.

That invariance is the finding. Whatever the entry triggers on, the median trade
travels about 0.7R in its favour before resolving. An entry carrying real
directional information would move that number. Nothing has.

### Standing tally after four sweeps

| | Best result |
|---|---|
| Bias vote rules (6) | -0.8 edge, z = -0.33 (inverted `no_pd_v2`) |
| Direction isolation | -3.4 edge, z = -1.03 (shorts only) |
| Entry triggers (2) | -1.9 edge, z = -1.20 (CISD shorts) |
| **Anything above its own benchmark** | **none** |

Forty-five configurations, nine bugs fixed, and the ceiling is "indistinguishable
from random". With 45 trials a winner would need t > 3 to be credible, and nothing
has cleared t = 0.

### One untested thing ICT actually teaches

Every run so far executes on 15m, which is ICT's *array* timeframe, not his
execution timeframe. His documented day-trade ladder is 1H bias, 15m context, **5m
execution**, and his stated method for improving R:R is to *shrink the stop by
dropping timeframes while leaving the target unchanged*.

That exact combination — a 5m structural stop against an unchanged HTF liquidity
target — has never been tested here, and it is the one configuration where MFE in R
terms could exceed target R rather than sitting at 0.7. The headwind is obvious and
quantified: a 3-point stop puts cost drag at 34% of R. Worth one run to find out,
and the answer is informative either way.

---

## Experiment 21 — MFE/MAE on 1m: the target is unreachable, and a wider stop will not help (July 2026)

Configurations tried to date: **40**. Excursion is pure measurement — the four
`directions` cells reproduced byte-identical trade counts, win rates and returns,
which is how I know the instrumentation changed nothing.

### Every trade's path, measured on 1-minute bars

| Cell | n | Target R | Median MFE | Median MAE | Ever reached target |
|---|---:|---:|---:|---:|---:|
| both | 310 | 1.59 | **0.70** | 1.13 | **24.5%** |
| long_only | 143 | 1.61 | 0.61 | 1.16 | 19.6% |
| short_only | 216 | 1.47 | 0.66 | 1.04 | 23.6% |
| ote_direction_off | 365 | 1.70 | 0.68 | 1.15 | 22.7% |

**The median trade travels 0.70R in its favour against a 1.59R target, and only
24.5% ever reach the target at all.** Median adverse excursion is 1.13R, i.e. the
median trade exceeds its stop.

### Split by outcome — the exits are fine, the entries are not

| Cell | MFE winners | MFE losers | MAE winners | MAE losers |
|---|---:|---:|---:|---:|
| both | 1.62 | **0.49** | 0.44 | 1.22 |
| long_only | 1.58 | 0.44 | 0.39 | 1.25 |
| short_only | 1.62 | 0.36 | 0.44 | 1.19 |

Trades bifurcate cleanly. Winners barely threaten the stop (MAE 0.44R) and just
clear the target (MFE 1.62R against a 1.59R target). Losers never get halfway
(MFE 0.49R) and then blow through the stop (MAE 1.22R).

**So no P&L is being lost to bad exit handling.** An entry either works almost
immediately or fails almost immediately. That narrows the problem to the entry's
directional accuracy, which the direction sweep already put at 3.8 sigma below
random on longs.

### This kills the wide-stop hypothesis

Experiment 18 concluded the binding constraint was `cost_share_of_R = 1.02 /
stop_points`, and that tripling R per trade was one of two ways out. That is now
falsified: **losers only ever travel 0.49R in their favour.** Widening the stop
cannot rescue a trade that never approached its target — it would only make each
loss larger in dollars while leaving the hit rate untouched.

The planned wide-stop geometry cell is therefore **dropped rather than run**, which
is the cheapest possible outcome for that hypothesis.

Nor does a nearer target work. Breakeven at target T against a 1R stop needs a
`1/(1+T)` win rate. At T = 0.70R, where roughly half of trades reach, breakeven
needs 59% — and only ~50% get there. The MFE distribution does not admit a
profitable target anywhere.

### What is left

The entry has no directional edge, and the geometry cannot manufacture one. The
remaining avenues, in order of what the evidence supports:

1. **A different entry trigger.** Research flagged FVG and CISD as the only
   causally clean ICT concepts; the current entry rests on order blocks, which are
   defined retroactively. A CISD entry — a body close through a known opening
   price — has never been tested here.
2. **Selectivity, not tuning.** 310 trades in a year at 15m against costs of ~11%
   of R. If only a small subset of setups carries the 24.5% target-reach rate,
   finding it matters more than any parameter.
3. **Accepting the answer.** Four sweeps and 40 configurations have produced
   nothing above its own random-walk benchmark. That is a legitimate result about
   this rule set on ES, not a tuning problem.

---

## Experiment 20 — The anti-edge is on the long side (July 2026)

Configurations tried to date: **36**. All on the 2023 screen, ~6 min a cell.

### The inversion test: signal is backwards, but correcting it only reaches zero

| Cell | n | WR | Coin-flip | Edge | z | PF | avg R |
|---|---:|---:|---:|---:|---:|---:|---:|
| no_pd_v2 normal | 365 | 26.8% | 35.9% | -9.1 | **-3.62** | 0.59 | -0.33 |
| no_pd_v2 **flipped** | 382 | 33.8% | 34.6% | -0.8 | -0.33 | 0.95 | -0.03 |
| no_pd_plurality normal | 371 | 27.2% | 35.8% | -8.6 | **-3.46** | 0.60 | -0.32 |
| no_pd_plurality **flipped** | 377 | 33.4% | 34.3% | -0.9 | -0.37 | 0.95 | -0.04 |
| all4_majority normal | 370 | 28.1% | 36.1% | -8.0 | **-3.20** | 0.58 | -0.31 |
| all4_majority **flipped** | 396 | 32.3% | 34.5% | -2.2 | -0.92 | 0.90 | -0.02 |

Flipping the bias moves every pair from ~3.4 sigma below its benchmark to
statistically indistinguishable from it. Profit factor goes 0.58-0.60 to 0.90-0.95
and signed avg R goes -0.32 to -0.03.

**So the signal points the wrong way, and correcting the sign yields a coin flip
rather than an edge.** It does not mirror cleanly because flipping selects the
opposite zones, so geometry changes too: stop 8.2 to 9.3, target 15.0 to 17.9.

### Direction isolation: longs are the problem

| Cell | n | WR | Coin-flip | Edge | z | PF | Return |
|---|---:|---:|---:|---:|---:|---:|---:|
| short_only | 216 | 33.8% | 37.2% | -3.4 | -1.03 | 0.73 | -25.8% |
| both | 310 | 28.4% | 37.1% | -8.7 | -3.17 | 0.60 | -52.2% |
| **long_only** | 143 | **22.4%** | 37.9% | **-15.5** | **-3.82** | 0.46 | -38.2% |

**Longs sit 15.5 points below their benchmark at z = -3.82. Shorts sit 3.4 below at
z = -1.03, which is not significant.** The anti-edge is concentrated almost entirely
on the long side, and it is worth noting 2023 was a grinding *uptrend* — losing
money on longs in a rising market is the striking part.

Caveat: long_only has 143 trades, under the 200 needed to trust a win rate. The gap
to shorts is large enough to act on as a hypothesis, not as a settled fact.

### Bug 3 confirmed by measurement: the OTE gate ignored its own direction

`detect_retracements` reports whether the current leg is bullish or bearish, but
`in_ote` was computed with `abs()` and never consulted it. A 70% pullback inside a
bullish leg could gate a short, and a 70% bounce inside a bearish leg could gate a
long — wrong half the time.

| | Trades | WR | Return |
|---|---:|---:|---:|
| Direction check ON | 310 | 28.4% | -52.2% |
| Direction check OFF (the bug) | 365 | 26.8% | -61.2% |

The fix removed 55 trades and improved return by **9 points**. It was a real bug.

### Regime validation, rebuilt

`backtest/regimes.py` is replaced. The old version hardcoded four one-week windows
picked by their realised return, and **three of the four fell inside the 2026
holdout** — running them during iteration would have spent it unnoticed.

The new approach is **attribution, not splicing**: run the span once, then split
monthly P&L by regime. Each month is labelled from the **prior** month's trend
efficiency and annualised volatility, so the label is knowable at the window's open
and a live system could act on it. Splicing was rejected because one month yields
~30 trades at 15m, it fragments the equity curve so drawdown stops meaning anything,
and it discards the regime transitions where drawdowns happen.

Measured on 2021-08..2024-12: 40 months labelled — trending_lowvol 13,
choppy_highvol 13, choppy_lowvol 7, trending_highvol 7.

Honest limit on the labels: prior-month volatility predicts next-month volatility
reasonably (choppy_highvol realised std 5.55% vs trending_lowvol 3.26%), but
prior-month trend efficiency barely predicts next-month efficiency. Treat the trend
half of each label as a guess about conditions, not a description of them.

`robustness()` reports how many regimes a config is profitable in, because earning
in one regime only is a regime bet rather than an edge — and that is the shape
overfitting takes when a sweep is scored on one aggregate number.

### A bug in the new code, caught by its own test

The efficiency ratio came out at **1.05** on a monotone series. `net` was measured
from the first daily *open* while `path` started at the first daily *close*, so net
covered a day path did not. Both are close-to-close now.

### Next

Log **MFE and MAE per trade** from the 1m data. If maximum favourable excursion
rarely reaches 1.5R even on winners, the target is unreachable by construction and
no amount of entry tuning fixes it. That is the measurement that would explain why
an 8-9 point stop against a 15-18 point target fails in a grind.

---

## Experiment 19 — Two miscalculations fixed; the fix made results worse (July 2026)

Configurations tried to date: **26**. Screening span 2023, ~6 min a cell, 6 cells
in parallel in about 8 minutes.

### Bug 1: the flagship setup picked the stalest zone in the window

`_find_fvg_ob_overlap` returned the **first** overlapping FVG+OB it found. Detector
output is ordered oldest-first, so "first" meant the oldest zone in a 500-1000 bar
window — and its low then set the stop. On a constructed case the stop came out
**102 points wide where the nearest zone gives 17**. The two sibling finders,
`_find_ob_entry` and `_find_fvg_entry`, already selected by distance. Only the
highest-priority setup did not.

### Bug 2: a full stop-out reported +1.0R

`rr_achieved` used `calc_risk_reward`, which takes `abs()` of both legs. So a
losing trade reported a *positive* R multiple, and the "Avg R:R" printed in every
report averaged +1.0 for each loss against ~+1.8 for each win. It read like
expectancy while being incapable of going negative. Added `realized_r`, signed.

The effect is immediate: `avg_rr` on the 2023 screen was +1.08 to +1.13 before and
is **-0.19 to -0.33 after** — that is the real expectancy per trade in R, and it
was previously invisible.

### The uncomfortable result: fixing bug 1 made everything worse

| Cell | Edge before | Edge after | Change | z after |
|---|---:|---:|---:|---:|
| no_pd_v2 | -2.7 | **-9.1** | -6.4 | **-3.62** |
| no_pd_plurality | -2.8 | **-8.6** | -5.8 | **-3.46** |
| all4_majority | -2.3 | **-8.0** | -5.7 | **-3.20** |
| all4_v3 | +0.8 | -3.6 | -4.4 | -1.49 |
| struct_liq_v2 | +0.4 | -3.4 | -3.8 | -1.30 |
| no_pd_v3 | -2.7 | -4.5 | -1.8 | -1.47 |

Edge is win rate minus that cell's own `stop/(stop+target)` benchmark, so it is
comparable across the geometry change. Median stop tightened from 9.2-10.9 points
to 8.2-9.2, and median target from 17.5 to ~15.

**The change is correct and the results got worse.** Selecting a zone that price
left 500 bars ago cannot be defended, and the sibling finders already did it right.
So the earlier numbers were leaning on the wide stop the bug happened to produce.
Reverting would be fitting the code to the backtest, which is not on the table.

### The finding that matters: the entry is reliably anti-predictive

Three cells now sit **3.2 to 3.6 sigma below** their own random-walk benchmark on
~370 trades each. That is not an absence of edge — it is exploitable information
pointing the wrong way, and at that sample size it is not noise.

A plausible mechanism: the nearest zone is nearest *because* price is sitting on
it, and a zone price is sitting on breaks about as often as it holds. Entering at
market with a stop just beyond it is then a coin flip with a tight stop, which the
cost model punishes at 11-12.6% of R.

**Next: the inversion test.** Added as a first-class `invert` sweep with an
`invert_bias` parameter rather than a monkeypatch, pairing each bias rule with its
inverse so the comparison is like for like. If flipping lands materially above the
benchmark, there is a sign or lag error in the entry logic and that is the bug. If
it mirrors to roughly zero, the signal carries nothing and the geometry was doing
all the work.

---

## Experiment 18 — Cost model fixed; the edge does not survive it (July 2026)

Configurations tried to date: **20**.

### Three defects in the cost model

Experiment 17 claimed "the entry signal works but costs eat exactly all of it".
Re-checking it found the claim was wrong in both directions, and the reason it went
unnoticed was that **the engine recorded only net P&L** — so the conclusion had to be
inferred from arithmetic rather than measured.

| Defect | Effect |
|---|---|
| Exit leg never paid the spread | Entry paid `SPREAD/2`, exit paid only slippage, under-charging 0.25 pt every trade |
| `close_position_manual` bypassed costs entirely | SESSION_END, circuit-breaker and backtest-end exits were free — 19% of exits |
| Nothing recorded what a round trip paid | The claim could not be checked |

Now every fill pays `SPREAD_POINTS / 2 + SLIPPAGE_POINTS`, so a round turn costs
1.00 point plus $1.25 commission — **$51.25 a contract on ES**. Manual closes go
through the same path. Each trade records `gross_pnl` and `costs`, and
`gross_pnl - costs == pnl_dollars` reconciles exactly on every cell.

Measured cost is **$89-102 per trade** at a mean 1.89 contracts, which is ~11% of R
and matches the `1.02 / stop_points` formula.

### The corrected result: the edge does not clear the bar

Same six bias cells, same 2021-07 to 2024-12 span, correct costs:

| Cell | n | Win rate | Coin-flip | Edge | z | Gross | Costs | Net | Max DD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| all4_majority | 1010 | 37.8% | 34.5% | +3.3 | 2.21 | +$43.4k | $92.3k | -$48.8k | 61% |
| all4_v3 | 961 | 38.0% | 34.9% | +3.1 | 2.02 | +$47.7k | $91.1k | -$43.4k | 59% |
| no_pd_plurality | 878 | 35.8% | 34.1% | +1.7 | 1.06 | +$22.6k | $74.9k | -$52.3k | 66% |
| no_pd_v2 | 888 | 35.9% | 34.2% | +1.7 | 1.07 | +$25.5k | $75.6k | -$50.1k | 66% |
| no_pd_v3 | 568 | 36.3% | 35.2% | +1.1 | 0.55 | +$16.1k | $53.2k | -$37.2k | 49% |
| struct_liq_v2 | 618 | 35.6% | 35.0% | +0.6 | 0.31 | -$3.4k | $51.7k | -$55.1k | 56% |

**The edge shrank from z = 3.07-4.29 to z = 0.31-2.21.** Nothing clears the t > 3 bar
for a data-mined result, and only two cells clear even t > 2.

The mechanism is exactly the one flagged as a risk: charging the exit leg flips
trades that exited near breakeven into losses, and `calc_stats` classifies wins by
`pnl_dollars > 0`. Win rate fell 40.2% to 37.8% on the best cell while its coin-flip
benchmark barely moved. **So part of the apparently significant edge in experiment 17
was an artefact of under-charged costs.**

### Where the money goes

Gross is positive on five of six cells, at $16k to $48k over 3.5 years. Costs are
$52k to $92k — **two to four times the gross edge.**

Gross expectancy on the best cell is $43.4k / 1010 = **$43 a trade**, about 4.8% of
R. Costs are ~11% of R. So the gross edge is under half of what it costs to collect.

### Net P&L by year — it is not one bad regime

| Cell | 2021 | 2022 | 2023 | 2024 |
|---|---:|---:|---:|---:|
| all4_majority | +1,035 | +11,358 | **-52,515** | -8,710 |
| all4_v3 | +14,316 | -15,356 | **-26,148** | -16,179 |
| no_pd_plurality | +11,647 | -19,968 | **-38,497** | -5,482 |
| no_pd_v2 | +15,887 | -23,214 | **-39,014** | -3,742 |
| no_pd_v3 | +5,456 | +14,194 | **-41,064** | -15,761 |
| struct_liq_v2 | -5,036 | -10,674 | **-25,305** | -14,102 |

2023 is worst but **2024 is negative for all six as well**, and only 2021 is broadly
positive. This is not a single-regime problem.

### The 2023 screen: no edge at all, even gross

The new screening span (2023 only, ~330 trades a cell, ~6 min) gives z between
**-1.06 and +0.30** on all six cells — indistinguishable from a coin flip — with
gross P&L between -$14.8k and +$6.8k. On the hardest year there is nothing for costs
to consume.

One surprise: **SESSION_END exits are profitable** on every cell, +$775 to +$8,075.
The forced 16:00 ET close is not the leak. The stop-to-target ratio is: the best cell
took 180 stops for -$153k against 92 targets for +$118k.

### What this means for direction

The binding arithmetic is `cost_share_of_R = 1.02 / stop_points`. At a 9-10 point
stop that is 11%, and gross expectancy is 4.8%. Two ways out, both testable:

1. **Roughly triple R per trade.** A 30-point stop puts costs at 3.4% of R instead of
   11%. The `geometry` sweep has a `liq_only_tight_stop` cell but **no wide-stop
   cell** — that is the obvious gap to fill next.
2. **Roughly triple the gross edge per trade**, which means better selection rather
   than better geometry. 350 trades a year is not a selective ICT model.

Screening should now run on 2023 by default (`--span screen`), since a config that
cannot clear a coin flip there is not worth a 25-minute confirmation run.

---

## Experiment 17 — Bias fix and the first real sweep (July 2026)

Results now live in `logs/experiments.jsonl`, one line per cell, and
`py main.py sweep-report` generates the ranking. This entry is the narrative; the
store is the data. Configurations tried to date: **8**.

### Two bugs in the bias function

`determine_ict_bias` produced a directional bias on about **1% of bars** and
returned **bullish zero times across 2025**, a year ES rose. It blocked 88.7% of
all bars, so nothing downstream could be measured.

1. **The raid factor abstained on every single bar** — 2,939 consecutive samples.
   It asked whether either side had been swept anywhere in the 200-bar window;
   with ~16 liquidity zones a bar at ~88% swept, the answer was always "both", so
   `swept_sell and not swept_buy` was never true. "3 of 4 aligned" was really
   unanimity. It now compares which side was swept **most recently**.
2. **Premium/discount votes bearish 97% of the time** in a rising market, so as a
   *direction* vote it is a standing short bias. ICT uses premium/discount to
   decide where to enter inside a bias, not which way to trade. It is now
   optional via `bias_factors_used`.

Fixing the raid factor alone moved bias from 1% to **44% directional**.

### Sweep: bias vote rules, 2021-07-25 to 2024-12-31, 15m

Geometry held at the ICT-faithful setting (liquidity-only targets, no 3R
fallback, R:R as a veto at 1.0). Circuit breaker off so the whole span is
measured.

> **P&L columns superseded by experiment 18** — this run under-charged costs.
> Trade counts, win rates and the edge over the benchmark are unaffected, because
> costs move P&L, not which barrier was hit first.

| Cell | Trades | Long/Short | Win rate | Coin-flip | Edge | z | PF | Return | Max DD |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| all4_majority | 1233 | 507/726 | 40.2% | 34.4% | **+5.8** | **4.29** | 1.00 | -1.9% | 45.7% |
| all4_v3 | 1036 | 448/588 | 39.0% | 34.2% | +4.8 | 3.26 | 0.97 | -14.7% | 45.7% |
| no_pd_plurality | 1103 | 523/580 | 38.6% | 34.0% | +4.6 | 3.23 | 0.97 | -16.0% | 45.6% |
| no_pd_v2 | 1090 | 530/560 | 38.4% | 34.0% | +4.4 | 3.07 | 0.97 | -15.7% | 49.4% |
| no_pd_v3 | 595 | 370/225 | 36.5% | 34.4% | +2.1 | 1.08 | 0.92 | -24.0% | 45.0% |
| struct_liq_v2 | 723 | 410/313 | 36.2% | 34.5% | +1.7 | 0.96 | 0.88 | -37.5% | 45.8% |

"Coin-flip" is `stop / (stop + target)` — the win rate a random walk gives for
that cell's own geometry. It is the only fair basis for comparing win rates
across different geometries.

### The good news: the entry signal now carries positive information

The old default sat **7.7 points below** its coin-flip benchmark, which is
anti-information. Four of six variants now sit **4.4 to 5.8 points above** it, at
z = 3.07 to 4.29. That clears the t > 3 bar Harvey/Liu/Zhu recommend for
data-mined results, and with only 8 configurations tried the multiple-testing
burden is small.

Long and short counts are now balanced and both sides win at similar rates
(37-42%), so the one-sided bias is gone.

### The bad news: costs — but the arithmetic below was WRONG, see experiment 18

> **Superseded.** The reasoning in this section was checked and does not hold, and
> the cost model it described was not what the code charged. The P&L figures in the
> table above are from a run that under-charged costs by roughly $33,000. Corrected
> numbers are in experiment 18. Kept here because the error is instructive.

What was published: "+5.8 points of win rate at 1.84 R:R gives +0.10R per trade;
1R is 11 ES points = $550; costs are ~$51 a contract = 9.3% of R; 1233 x $51 ≈
$63k of costs against ~$67k of gross edge."

Three things were wrong. The code charged **$26.25** a contract, not $51 — the
exit leg never paid the spread and manual closes paid nothing. The mean trade is
**1.89 contracts**, so 1R is nearer **$870** than $549, and a per-contract figure
was being applied per trade. And the naive win/loss expectancy model ignores that
19% of exits are forced session-end closes at neither barrier, so it predicts
+$97k of gross against an actual net of -$1.9k.

The aggregate looked plausible only because two errors partly cancelled.

**The one part that survives:** cost drag as a share of R is `~1.02 / stop_points`,
independent of position size, because commission, spread and slippage all scale
with contracts exactly as risk does. That describes the *intended* model, which is
what experiment 18 implements — the code simply was not charging it.

**Root cause: the engine recorded only net P&L.** Nothing stored what a round trip
paid, so the claim had to be inferred instead of measured. That is now fixed —
every trade records `gross_pnl` and `costs`, and `gross_pnl - costs == pnl_dollars`
holds by construction.

### 2023 is the killer, and it is not the 2022 bear market

Yearly P&L, all six cells:

| Cell | 2021 | 2022 | 2023 | 2024 |
|---|---:|---:|---:|---:|
| all4_majority | +6,220 | +23,480 | **-38,216** | +6,662 |
| all4_v3 | +16,827 | -5,047 | **-26,386** | -139 |
| no_pd_plurality | +13,977 | +312 | **-39,617** | +9,320 |
| no_pd_v2 | +21,101 | -8,078 | **-41,685** | +12,945 |
| no_pd_v3 | +6,917 | +18,506 | **-35,195** | -14,253 |
| struct_liq_v2 | -2,911 | -12,020 | -9,010 | -13,526 |

Every variant collapses in 2023 and most are positive in 2021 and 2024. 2023 was
a grinding low-volatility uptrend in ES, which is the regime a sweep-and-reverse
method should struggle in. This looks like a real regime dependency, not noise.

### What to focus on

1. **Cost per trade against R.** This is the binding constraint. Costs are 9.3%
   of R at an 11-point stop; below ~5% needs a stop above 20 points, or many
   fewer trades. Test both, and test MES to see whether the smaller contract
   changes the ratio.
2. **The 2023 regime.** Find what breaks. A trend filter is the obvious
   hypothesis — if the method is counter-trend by construction, it needs to stand
   aside in a grind.
3. **Selectivity.** ~350 trades a year is not an ICT model. Filtering to the best
   setups cuts total cost drag directly. `score_slope` is now mildly positive on
   most cells, so a higher `min_score` is worth a sweep.
4. **Drawdown.** 45-49% on every cell, with the breaker off. Even a profitable
   version is untradeable at that level; concurrent-position and sizing rules
   need their own sweep.

### What to drop

- **`struct_liq_v2`** (z=0.96, -37.5%) and **`no_pd_v3`** (z=1.08, -24.0%). Both
  fail significance and lose the most. Structure plus liquidity draw alone is too
  thin, and requiring 3 of 3 is too strict.
- **Not yet resolved:** whether premium/discount belongs in the vote. The `all4_*`
  cells that keep it rank marginally higher, but the `no_pd_*` cells are better
  balanced long/short. Keep both arms in future sweeps.

### Causality verified on real data

The 22 synthetic causality tests now also run against real ES bars, and finding
the right invariant was itself informative. **Full incremental stability does not
hold**: appending 200 bars to a 700-bar window erased 1 swing, 1 BOS and 3 order
blocks. That is legitimate invalidation — live trading sees the same revision.

What does hold, and what "no look-ahead" actually means, is the asymmetry:
**no signal is ever created at a settled past bar.** Later data may invalidate a
signal but never reveals one retroactively. The confirmation-lag boundary
measured 8 bars, so the tests exclude a 15-bar margin and assert no creation
before it.

---

## Experiment 16 — First run on real ES data (July 2026)

Dataset: `historical/ES-5y/glbx-mdp3-20210724-20260723.ohlcv-1m.dbn.zst`, Databento
GLBX.MDP3 `ohlcv-1m`, `ES.FUT` parent symbology, 2021-07-25 to 2026-07-23. 2,826,688
records, 1,769,803 front-month bars after dropping spreads and stitching. Validated with
`py main.py validate-data` — see *Dataset validation* below.

**The strategy loses money on real ES data.** Every earlier positive number in this file
came from a synthetic random walk.

Default strategy, 15m entry, `--min-score 60`, 2025 calendar year:

| | As shipped | Circuit breaker disabled (probe) |
|---|---:|---:|
| Trades | 17 | 114 |
| Win rate | 17.6% | **13.2%** |
| Profit factor | 0.19 | 0.32 |
| Net P&L | -$7,677 (-7.7%) | **-$40,048 (-40.0%)** |
| Max drawdown | 10.1% | 43.7% |
| Max loss streak | 9 | 24 |
| Losing months | 2 of 2 | 9 of 11 |

As shipped, the latching circuit breaker fires on **2025-02-05** at 10.1% drawdown and
blocks the remaining eleven months, so the run reports only 17 trades. Raising the limit
in-process (a probe, nothing on disk changed) shows the rest of the year: 99 losses in 114
trades.

**This is not one bad month.** It loses in nine of eleven months.

Diagnosis so far, measured on 2025 data:

- Median stop 14.12 points, median target 33.25 points — about 2.35:1, as `MIN_RR_RATIO`
  demands.
- Median 15m ATR is 5.93 points and the median 15m bar range is 5.25 points.
- So the stop sits at **2.4x ATR** — it is *not* too tight — while the target sits at
  **5.6x ATR**.
- Reaching a 5.6-ATR target without first retracing 2.4 ATR is a demanding ask on a 15m
  chart, and 87% of trades hit the stop instead.
- Break-even at 2.35:1 needs roughly a 30% win rate. The strategy gets 13%.

Either the entry has no directional edge, or the stop-and-target geometry is wrong for
15m ES. That needs its own investigation; it is not a data problem.

Two side notes: only **5 setups** were skipped for a stop too wide to afford one ES
contract, and only **1 of 17 trades** entered on a bar that opened after a session break,
so neither of those is the issue.

**The latching circuit breaker makes multi-year research runs uninformative** — you see
nothing past the first 10% drawdown. Worth a separate switch for research runs.

### Dataset validation

`py main.py validate-data <file>` reports:

- Integrity clean across all 2,826,688 records — no `high < low`, no open or close outside
  the bar, no non-positive volume, no duplicate keys, no nulls.
- Zero Saturday bars. CME's own trading-hours page notes Saturday hours are "for internal
  testing only".
- 41 short sessions of 1,293, all explained: 40 early closes, 1 thin holiday. **Zero
  unexplained.**
- 301 gaps over an hour, all classified: 252 weekend, 38 holiday, 6 extended holiday, 5
  weekend plus holiday.
- One anomaly: a single flat bar inside the 17:00 ET maintenance halt at **2023-10-30**,
  volume 3000. One bar in 1.77 million.
- `condition.json`: 9 degraded days, of which 8 are complete anyway. **2025-11-28** is the
  only material one — 510 bars missing, no overnight session.

### Roll dates now match CME exactly

The roll is derived from daily traded volume rather than a hardcoded table. All six dates
that overlap CME's published [Equity Index Roll Dates](https://www.cmegroup.com/trading/equity-index/rolldates.html)
match its "customary roll date" column:

| Contract | Measured | CME customary roll |
|---|---|---|
| ESH5 | 2025-03-17 | 2025-03-17 |
| ESM5 | 2025-06-16 | 2025-06-16 |
| ESU5 | 2025-09-15 | 2025-09-15 |
| ESZ5 | 2025-12-15 | 2025-12-15 |
| ESH6 | 2026-03-16 | 2026-03-16 |
| ESM6 | 2026-06-15 | 2026-06-15 |

The retired `ES_ROLL_DATES` table was 4 days early on all four rolls it covered. CME's rule
is "the Monday prior to the third Friday" — 4 days before expiry, not the 8 the old comment
assumed.

**ESM6 is why symbols must not be parsed.** Its expiry is 2026-06-18, not the third Friday
(2026-06-19), because that Friday is Juneteenth. Ordering contracts by last observed bar
sidesteps this and the one-digit-year ambiguity (`ESM5` could be 2025 or 2035) together.

### Warning: CME normalization changes 2026-08-08

Databento is [replacing its CME normalization](https://databento.com/blog/cme-normalization-changes-2026-07)
on **2026-08-08**, and the change applies **retroactively to the full historical dataset**.
Definition records will publish one row per strategy leg instead of one per strategy. The
`ohlcv-1m` record layout is unchanged, so this dataset should be unaffected, but pin this
snapshot and re-validate after the cutover before comparing new results with these.

---

## Experiment 15 — Audit fixes and adapter rewrite (July 2026)

Same input, same settings, before and after the seven fixes. Run on
`historical/SYNTH-ES.csv`, `--entry-tf 15min`, `--min-score 60`, 8,437 bars.

| Metric | Before | After |
|---|---:|---:|
| Trades | 38 | 15 |
| Win rate | 34.2% | 26.7% |
| Profit factor | 0.49 | 0.66 |
| Net P&L | -$8,279.93 | -$2,224.62 |
| Max drawdown | 10.86% (realized only) | 7.93% (marked to market) |
| Avg R:R | 0.63 | 0.99 |
| Skipped, stop too wide | n/a | 90 |
| **Run time** | **364.8 s** | **88.8 s** |
| **Per bar** | **43.24 ms** | **10.53 ms** |

The trade count falls because the evening `SESSION_END` stubs are gone and 90
setups now have stops too wide to afford a single ES contract.

Same fixes at `--entry-tf 5min` over the same file: 25,409 bars, 312.5 s,
**12.30 ms/bar**, 69 trades, 37.7% win rate, PF 1.14, 10.2% max drawdown, 150
skipped for a too-wide stop. That puts a full year at 5m entry near **21
minutes**, against roughly 77 before.

**This is synthetic data.** `historical/SYNTH-ES.csv` is a random walk with no
weekend gap, no daily halt and no holidays. It exercises the engine, not the
strategy — the P&L above says nothing about whether the strategy works.

### Where the speed came from

Profiling showed 684,000 Python calls per bar. `ict/smc_patched.py` is already
vectorized and accounted for 13% of the time; about 85% went to
`ict/smc_adapter.py` converting the vectorized output into dicts one cell at a
time with `result["BOS"].iloc[i]` inside a loop over every row. That rebuilds
the column on each pass — 903,565 `DataFrame.__getitem__` calls per 200 bars —
while the detector output is only 1-14% dense.

The five conversion loops and `ict/displacement.py` now pull columns into numpy
once and visit only the rows carrying a signal, via `np.flatnonzero`.
`get_windowed_data` uses `searchsorted` instead of masking and copying the whole
history every bar. Both are pure refactors: the trade list came back identical
apart from the randomly generated position id.

`vectorbt` was in `requirements.txt` and imported nowhere. It has been removed.
It would not have helped — it vectorizes signal arrays over a price series, and
ICT detection is path-dependent and stateful.

---

## Data Sources

### Databento ES 1-Year (1m OHLCV)
- **File:** `historical/ES-1year-1m/glbx-mdp3-20250407-20260406.ohlcv-1m.csv`
- **Range:** Apr 7, 2025 - Apr 6, 2026
- **Bars:** ~500,000+ (full 23-hour sessions including overnight)
- **Format:** Databento CSV with `ts_event`, `symbol` columns, multi-contract with stitching
- **Notes:** Includes many low-volume overnight/off-hours bars that dilute resampled candles. Produced fewer trades than IBKR data on the same date range — likely because off-hours bars change the resampled HTF structure.

### IBKR ES 6-Month (1m OHLCV)
- **File:** `historical/ES-90d-full.ohlcv-1m.csv`
- **Range:** Oct 10, 2025 - Apr 9, 2026
- **Bars:** ~154,055 (full 23-hour sessions, 5PM ET session-close anchoring)
- **Format:** IBKR download with `timestamp` column, single continuous series
- **Notes:** Better trading-hours coverage than Databento for ES futures backtesting. Produces more reliable results because bar resampling reflects actual traded sessions.

### IBKR ES 90-Day Original (1m OHLCV)
- **File:** `historical/ES-20260108-20260408.ohlcv-1m.csv` (superseded by 6-month file)
- **Range:** Jan 8, 2026 - Apr 8, 2026
- **Bars:** 30,787 (initial download with broken session anchoring — most weekdays only had ~260 bars/evening session)
- **Notes:** First IBKR download attempt. Session anchoring was later fixed to use 5PM ET close, producing full ~1,380 bars/day.

---

## Strategy Descriptions

### Default Strategy (Confluence Scoring)
- Full ICT detection pipeline: smc_patched (swings, BOS/CHoCH, FVGs, OBs, liquidity, retracements, PDH/PDL) + custom detectors (displacement, kill zones, Fibonacci/OTE, ATR) + advanced detectors (Breaker Blocks, IFVG, PO3/Judas Swing)
- Confluence scoring 0-100 with 17 weighted factors
- Entry priority: FVG+OB overlap > FVG+OTE (futures only require OTE for standalone FVG) > standalone FVG (non-futures only)
- Standalone OB filtered out for futures
- 4-factor HTF bias: structure direction + liquidity draw + premium/discount + raid status

### ICT 2022 Model Strategy (`--strategy ict_2022`)
- Only uses smc_patched detectors (no custom detectors, no confluence scoring)
- Temporal sequence detection: sweep sell/buy-side liquidity -> MSS (CHoCH) on entry TF -> enter on FVG retracement
- Kill zones: London 3-5 AM ET, NY 7-11 AM ET
- Min 1:3 R:R
- 4-factor HTF bias determination

### Silver Bullet Strategy (`--strategy silver_bullet`)
- Same sweep->MSS->FVG logic as ICT 2022
- Restricted to three 1-hour windows: 3-4 AM ET (London), 10-11 AM ET (NY AM), 2-3 PM ET (NY PM)
- Entire sweep->MSS->FVG sequence must form within the active window
- Min 1:2 R:R

---

## Experiment Results

### 1. Initial Backtest — Databento ES, 2 Weeks, Default Strategy

**Date run:** Apr 8, 2026
**Data:** Databento ES 1-year
**Period:** Mar 25 - Apr 6, 2026
**Config:** Kill zones ON, trade management OFF, spread/slippage OFF, threshold 60

| Entry TF | Trades | Win Rate | Net P&L | Notes |
|----------|--------|----------|---------|-------|
| 5min | 0 | — | $0 | Low confluence skips: 261, no-trade: 77 |
| 15min | 0 | — | $0 | Low confluence skips: 83, no-trade: 2 |

**Finding:** Zero trades. Only 2 weeks of data gave too few daily/4H bars for HTF bias detection (11 daily bars, 0 swings detected). Led to implementing HTF warmup (loading 90 extra days before --start).

---

### 2. FVG+OB Overlap Only Strategy (Experimental, Reverted)

**Date run:** Apr 8, 2026
**Data:** Databento ES 1-year with 90-day HTF warmup
**Period:** Mar 25 - Apr 6, 2026
**Config:** FVG+OB overlap only (no score), kill zones ON, no trade management

| Entry TF | Trades | Win Rate | Net P&L | Notes |
|----------|--------|----------|---------|-------|
| 5min | 4 | 25% | -$1,861 | All SHORT, bearish bias period |
| 15min | 0 | — | $0 | FVG+OB overlaps too rare at 15min granularity |

**Finding:** FVG+OB overlap is too selective alone — misses many setups. Strategy was reverted.

---

### 3. ICT 2022 Model + Silver Bullet — Databento ES, 3 Months

**Date run:** Apr 8, 2026
**Data:** Databento ES 1-year with HTF warmup
**Period:** Jan 1 - Apr 6, 2026
**Config:** Kill zones ON (per strategy), no trade management, no spread

| Strategy | Entry TF | Trades | Win Rate | Net P&L | Notes |
|----------|----------|--------|----------|---------|-------|
| ICT 2022 | 5min | 13 | 0% | -$10,324 | All SHORT into uptrend, 10.3% DD |
| Silver Bullet | 5min | 7 | 0% | -$4,051 | Across London/NY AM/NY PM windows |

**Finding:** Both strategies only found SHORT setups (bearish HTF bias) during a bullish period. 0% win rate. HTF bias was detecting bearish from pullbacks while the broader trend was bullish. Led to investigating bias detection improvements.

---

### 4. ICT 2022 Model + Silver Bullet — Databento, 1 Month

**Date run:** Apr 8, 2026
**Data:** Databento ES 1-year with HTF warmup
**Period:** Mar 8 - Apr 6, 2026

| Strategy | Entry TF | Trades | Win Rate | Net P&L |
|----------|----------|--------|----------|---------|
| ICT 2022 | 5min | 6 | 17% | -$4,112 |
| Silver Bullet | 5min | 4 | 50% | -$893 |
| ICT 2022 | 15min | 1 | 100% | +$460 |
| Silver Bullet | 15min | 0 | — | $0 |

**Finding:** Silver Bullet at 50% WR outperformed ICT 2022 (17% WR) on 5min. 15min too coarse for Silver Bullet windows (only 4 bars per window).

---

### 5. HTF Bias Disabled Test — All Strategies, 3 Days

**Date run:** Apr 8, 2026
**Data:** IBKR ES 90-day (full sessions)
**Period:** Apr 5-8, 2026
**Config:** HTF bias check REMOVED, kill zones ON

| Strategy | Entry TF | Trades | Win Rate | Net P&L | Notes |
|----------|----------|--------|----------|---------|-------|
| ICT 2022 | 1min | 3 | 0% | -$2,561 | All SHORT into rally |
| Silver Bullet | 1min | 0 | — | $0 | — |
| ICT 2022 | 5min | 5 | 0% | -$4,940 | All SHORT |
| Silver Bullet | 5min | 2 | 0% | -$2,000 | All SHORT |
| ICT 2022 | 15min | 2 | 0% | -$2,000 | All SHORT |
| Silver Bullet | 15min | 1 | 0% | -$804 | — |

**Finding:** Without HTF bias filter, strategies took bearish sequences that happened to be detected, all resulting in losses during a bullish 3-day period. HTF bias was re-enabled.

---

### 6. HTF Bias Re-enabled — Same 3 Days

**Config:** HTF bias ON (was bearish for this period), kill zones ON

Results were identical to #5 — the HTF bias was already bearish, so enabling/disabling didn't change which trades were taken. All trades aligned with the bearish bias but the 3-day period was a counter-trend bounce.

---

### 7. Default Strategy — IBKR 90-Day Data, Full Period

**Date run:** Apr 8, 2026
**Data:** IBKR ES 90-day
**Period:** Full range (no --start), ~3 months
**Config:** Kill zones ON, trade management OFF, threshold 60

| Entry TF | Trades | Win Rate | Net P&L | PF | Max DD |
|----------|--------|----------|---------|-----|--------|
| 15min | 62 | — | varies | — | — |

This was used as baseline for optimizer comparison.

---

### 8. Walk-Forward Threshold Optimization — IBKR 90-Day, 15min

**Date run:** Apr 8, 2026
**Data:** IBKR ES 90-day
**Config:** Kill zones ON, trade management OFF
**Split:** 70% train (Jan-Mar), 30% test (Mar-Apr)

| Threshold | Train Trades | Train WR | Train PF | Train P&L | Train DD |
|-----------|-------------|----------|----------|-----------|----------|
| 30 | 67 | 31.3% | 1.42 | +$13,062 | 7.9% |
| 40 | 59 | 30.5% | 1.45 | +$12,911 | 7.9% |
| **50** | **54** | **31.5%** | **1.53** | **+$14,540** | **7.0%** |
| 60 | 25 | 16.0% | 0.35 | -$10,759 | 10.8% |
| 70 | 5 | 40.0% | 1.51 | +$1,023 | 2.0% |
| 80 | 1 | 0.0% | 0.00 | -$1,000 | 1.0% |

**Best threshold:** 50 (PF 1.53)
**Test result (threshold=50):** 0 trades (choppy Mar-Apr period)

**Finding:** Threshold 60 was the worst performer — too selective, only 25 trades with 16% WR. Threshold 50 was optimal. However, test period produced no trades regardless of threshold.

---

### 9. Walk-Forward Optimization — Databento Full Year, 15min

**Date run:** Apr 8, 2026
**Data:** Databento ES 1-year (full, no --start)
**Config:** Kill zones ON, trade management OFF
**Split:** 70% train (Apr-Dec 2025), 30% test (Dec 2025 - Apr 2026)

| Threshold | Train Trades | Train WR | Train PF | Train P&L | Train DD |
|-----------|-------------|----------|----------|-----------|----------|
| 30 | 54 | 74.1% | 12.97 | +$211,113 | 2.1% |
| 40 | 54 | 74.1% | 12.97 | +$211,113 | 2.1% |
| 50 | 47 | 70.2% | 11.84 | +$160,050 | 2.1% |
| 60 | 44 | 70.5% | 11.66 | +$149,704 | 2.1% |
| 70 | 34 | 64.7% | 10.77 | +$96,818 | 2.1% |
| 80 | 10 | 60.0% | 9.29 | +$18,546 | 1.1% |

**Best threshold:** 30 (but 30-40 identical — no setups scored 30-39)
**Test result (threshold=30):** 2 trades, 0% WR, -$1,990

**Finding:** Train period (2025 uptrend) showed exceptional results across all thresholds. Test period (choppy Dec-Apr) failed. Classic regime change — strategy excels in trending markets, struggles in ranging/choppy conditions. Threshold 60 recommended as best quality filter (removes weakest setups while keeping 44/54 trades).

---

### 10. Walk-Forward Optimization — IBKR 6-Month, 1min

**Date run:** Apr 9, 2026
**Data:** IBKR ES 6-month
**Config:** Kill zones OFF, trade management OFF
**Split:** 70% train (Oct-Feb), 30% test (Feb-Apr)

| Threshold | Train Trades | Train WR | Train PF | Train P&L | Train DD |
|-----------|-------------|----------|----------|-----------|----------|
| 30-60 | 51 | 21.6% | 0.51 | -$8,425 | 9.4% |
| 70 | 31 | 19.4% | 0.28 | -$9,742 | 10.1% |
| 80 | 25 | 8.0% | 0.03 | -$11,539 | 11.5% |

**Test result (threshold=30):** 78 trades, 38.5% WR, PF 1.46, +$17,550

**Finding:** 1min train period was unprofitable, but test period was solidly profitable. The 1min timeframe has different characteristics than 5min/15min — noisier on train but adapted well to the Feb-Apr regime.

---

### 11. Kill Zones OFF — Walk-Forward Optimization, IBKR 6-Month

**Date run:** Apr 9, 2026
**Data:** IBKR ES 6-month
**Config:** Kill zones OFF, trade management OFF
**Split:** 70% train, 30% test

#### 15min Results

| Threshold | Train Trades | Train WR | Train PF | Train P&L | Train DD |
|-----------|-------------|----------|----------|-----------|----------|
| 30-50 | 87 | 40.2% | 2.04 | +$31,292 | 8.7% |
| 60 | 86 | 40.7% | 2.06 | +$31,532 | 8.7% |
| **70** | **83** | **39.8%** | **2.08** | **+$31,564** | **8.7%** |
| 80 | 73 | 37.0% | 1.95 | +$23,758 | 8.9% |

**Best threshold:** 70 (PF 2.08)
**Test (threshold=70):** 27 trades, 48.1% WR, PF 1.36, +$3,357, 5.6% DD

#### 5min Results

| Threshold | Train Trades | Train WR | Train PF | Train P&L | Train DD |
|-----------|-------------|----------|----------|-----------|----------|
| **30-50** | **224** | **35.7%** | **1.98** | **+$85,607** | **9.6%** |
| 60 | 222 | 35.6% | 1.65 | +$44,676 | 9.6% |
| 70 | 211 | 35.5% | 1.76 | +$49,049 | 7.3% |
| 80 | 193 | 35.2% | 1.73 | +$44,502 | 7.5% |

**Best threshold:** 30 (PF 1.98)
**Test (threshold=30):** 53 trades, 41.5% WR, PF 1.68, +$11,524, 12.1% DD

**Finding:** Removing kill zones significantly improved results. The strategy finds profitable setups throughout the trading day. 5min without kill zones is the standout performer: 224 trades, PF 1.98, +$85k on train, confirmed with PF 1.68 on test.

---

### 12. Default Strategy — IBKR 6-Month, 2 Months, New Bias System

**Date run:** Apr 9, 2026
**Data:** IBKR ES 6-month
**Period:** Feb 8 - Apr 9, 2026
**Config:** Kill zones OFF, trade management OFF, 4-factor ICT bias, threshold 60, standalone OB filtered, FVG requires OTE for futures

| Entry TF | Trades | Win Rate | Net P&L | PF | Max DD |
|----------|--------|----------|---------|-----|--------|
| 5min | 23 | 13.0% | -$8,786 | 0.36 | 10.5% |
| 15min | 60 | 35.0% | +$4,636 | 1.17 | 10.2% |

**15min Setup Breakdown:**

| Setup | Trades | Win Rate | Net P&L |
|-------|--------|----------|---------|
| FVG+OB overlap | 19 | 47% | +$6,700 |
| Fair Value Gap | 41 | 29% | -$2,064 |

**Finding:** 15min profitable, 5min struggled. FVG+OB overlap is the only profitable setup. Led to filtering standalone FVG and requiring OTE for FVG entries on futures.

---

### 13. Setup Type Performance Analysis — 5 Month, 15min

**Date run:** Apr 9, 2026
**Data:** IBKR ES 6-month
**Period:** Nov 9, 2025 - Apr 9, 2026
**Config:** Kill zones OFF, trade management OFF, threshold 60

**By Setup Type:**

| Setup | Trades | Win Rate | Avg Win | Avg Loss | Net P&L |
|-------|--------|----------|---------|----------|---------|
| FVG+OB overlap | 15 | 33.3% | +$1,105 | -$582 | +$1,451 |
| Fair Value Gap | 28 | 14.3% | +$3,856 | -$1,021 | -$1,938 |

**By Direction + Setup:**

| Direction | Setup | Trades | Win Rate | Net P&L |
|-----------|-------|--------|----------|---------|
| SHORT | FVG+OB overlap | 4 | 50.0% | -$73 |
| LONG | FVG+OB overlap | 11 | 27.3% | +$1,524 |
| LONG | Fair Value Gap | 15 | 20.0% | +$3,182 |
| SHORT | Fair Value Gap | 13 | 7.7% | -$5,120 |

**By Confluence Score:**

| Score Range | Trades | Win Rate | Net P&L |
|-------------|--------|----------|---------|
| 70-79 | 4 | 25.0% | +$4,502 |
| 90-100 | 22 | 27.3% | -$2,871 |
| 80-89 | 14 | 14.3% | -$1,062 |
| 60-69 | 3 | 0.0% | -$1,056 |

**Finding:** SHORT standalone FVG is terrible (7.7% WR). Higher confluence scores don't correlate with better performance. Led to filtering standalone FVG for futures and requiring OTE confirmation.

---

### 14. Trade Management Comparison — IBKR 6-Month, 5min

**Date run:** Apr 11, 2026
**Data:** IBKR ES 6-month
**Period:** Full range
**Config:** Kill zones OFF, threshold 30, FVG+OTE filter active

| | TM OFF | TM ON | Delta |
|---|---|---|---|
| **Net P&L** | +$72,943 (+72.9%) | +$36,785 (+56.2%) | -$36,158 |
| **Total Trades** | 242 | 328 | +86 |
| **Win Rate** | 34.3% | 40.9% | +6.6% |
| **Profit Factor** | 1.71 | 1.33 | -0.38 |
| **Max Drawdown** | 10.9% | 8.9% | -2.0% |

**TM OFF Setup Breakdown:**

| Setup | Trades | Win Rate | Net P&L |
|-------|--------|----------|---------|
| FVG+OB overlap | 214 | 35% | +$52,449 |
| FVG+OTE | 28 | 32% | +$20,494 |

**TM ON Setup Breakdown:**

| Setup | Trades | Win Rate | Net P&L |
|-------|--------|----------|---------|
| FVG+OB overlap | 284 | 40% | +$22,729 |
| FVG+OTE | 44 | 48% | +$14,056 |

**Finding:** Trade management (50% close at 1R + breakeven) reduces total P&L by ~50% but improves risk profile (lower drawdown, higher win rate). The partial close caps upside on big winners which is where bulk profit came from. TM is better for risk-averse trading; TM OFF is better for maximum returns.

---

## Key Findings Summary

### What Works
1. **FVG+OB overlap** is consistently the best entry type across all tests
2. **Kill zones OFF** significantly outperforms KZ ON — profitable setups exist throughout the day
3. **15min entry** is the most reliable timeframe for ES futures
4. **4-factor ICT bias** (structure + liquidity draw + premium/discount + raid status) improves direction accuracy
5. **IBKR data** produces more reliable backtest results than Databento for ES (better trading-hours coverage)

### What Doesn't Work
1. **Standalone FVG entries** on futures — consistently unprofitable (7-14% WR)
2. **Standalone OB entries** on futures — filtered out, too noisy
3. **SHORT standalone FVG** — worst performer across all tests (7.7% WR)
4. **Higher confluence scores** don't correlate with better performance (70-79 outperforms 90-100)
5. **ICT 2022 / Silver Bullet strategies** in choppy markets — 0% WR when market regime doesn't trend

### Regime Dependency
- **Trending markets (2025 uptrend):** All strategies perform well, 60-74% WR, PF 10+
- **Choppy/reversal markets (Dec 2025 - Apr 2026):** Dramatically reduced performance, few trades, frequent losses
- The strategy needs a regime filter or should reduce position size during choppy periods

### Optimal Configuration (Current Best)
- **Data:** IBKR 6-month ES data
- **Entry TF:** 5min (most trades, best absolute returns) or 15min (higher WR, fewer trades)
- **Kill zones:** OFF
- **Threshold:** 30-50 (30 and 50 often identical, meaning all setups score >= 50)
- **Trade management:** OFF for max P&L, ON for lower drawdown
- **Entry types:** FVG+OB overlap + FVG+OTE only (no standalone FVG/OB on futures)
- **Bias:** 4-factor ICT bias (structure + liquidity + premium/discount + raids)
- **Spread/slippage:** Not yet tested with realistic values (0.50 spread + 0.25 slippage)

---

## Configuration History

| Date | Change | Impact |
|------|--------|--------|
| Apr 8 | HTF warmup (90 days before --start) | Fixed 0-trade issue when using date filters |
| Apr 8 | Added ICT 2022 + Silver Bullet strategies | New strategy paths, temporal sequence detection |
| Apr 8 | IBKR historical data download | Full 23-hour session coverage, 5PM ET anchoring |
| Apr 9 | Spread/slippage modeling (defaults 0.0) | Infrastructure ready, not yet tested with nonzero values |
| Apr 9 | Global circuit breaker (latching, force-close) | Enforces 10% DD limit, closes all positions |
| Apr 9 | Per-asset SL ATR multiplier | ES=0.5x, BTC=1.5x ATR buffer |
| Apr 9 | Filter standalone OB on futures | Removed noisy entries |
| Apr 9 | Silver Bullet NY AM bonus (+5 points) | 10-11 AM ET window gets extra confluence |
| Apr 9 | Breaker Block + IFVG detectors | New confluence factors (8 + 6 points) |
| Apr 9 | Power of 3 / Judas Swing detector | Asian range sweep detection (10 points) |
| Apr 9 | Trade management (partial TP + trailing SL) | 50% close at 1R, breakeven, trail remainder |
| Apr 9 | TP targeting nearest-first | Picks closest valid target instead of first meeting min R:R |
| Apr 9 | Walk-forward threshold optimizer | Parallel execution, train/test split with HTF warmup |
| Apr 9 | 4-factor ICT bias determination | Structure + liquidity draw + premium/discount + raid status |
| Apr 9 | FVG+OTE requirement for futures | Standalone FVG must be in OTE zone (61.8-79%) |
| Apr 9 | Kill zone toggle (ENFORCE_KILL_ZONES) | Can disable KZ filtering via config flag |
| Apr 9 | Displacement divide-by-zero fix | Guard against NaN/zero ATR in consecutive check |
| Apr 11 | Kill zones OFF globally | ENFORCE_KILL_ZONES=False wired through backtest + live + CLI |
| Apr 11 | ICT bias strict 3-of-4 rule | 2-1/2-0 splits now return neutral instead of directional |
| Apr 11 | Optimizer fails on worker errors | No more silent zeroed results from crashed thresholds |
| Jul 24 | Stitching trims both ends of each contract | Back-month bars no longer share timestamps with front month |
| Jul 24 | Panama back-adjustment at rolls | Roll steps stop reading as FVGs |
| Jul 24 | Stable sort before dedup | Stitching is deterministic across runs |
| Jul 24 | Session-end close bounded to 16:00-17:00 ET | Evening trades no longer closed one bar after entry |
| Jul 24 | POINT_VALUE in backtest P&L, whole contracts | Real ES/MES sizing; wide stops now skip instead of trading |
| Jul 24 | Spread 0.50, slippage 0.25, commission 1.25 | Results are net of costs |
| Jul 24 | Mark-to-market drawdown each bar | Max DD and circuit breaker see open positions |
| Jul 24 | Daily/4H bars anchored to 18:00 ET session open | PDH/PDL and daily bias cover one CME session |
| Jul 24 | smc_adapter + displacement vectorized | 43.24 -> 10.53 ms/bar, identical output |
| Jul 24 | get_windowed_data uses searchsorted | Removes the O(n^2) term that grows with dataset size |
| Jul 24 | Dropped vectorbt; added .dbn loader | Unused dependency removed; Databento DBN files load directly |
| Jul 24 | Raid bias factor compares latest sweep per side | Was abstaining on 100% of bars; bias 1% -> 44% directional |
| Jul 24 | Premium/discount vote made optional | Voted bearish 97% of the time in a rising market |
| Jul 24 | Bias vote rule parameterised | min_votes / majority / plurality, sweepable |
| Jul 24 | Targets liquidity-only, R:R demoted to a veto | 3R fallback had accounted for 88 of 95 trades |
| Jul 24 | backtest/params.py override module | Config constants bind at import; sweeps were no-ops without this |
| Jul 24 | backtest/experiments.py + sweeps.py + logs/experiments.jsonl | Append-only experiment store; ranking is generated, not typed |
| Jul 24 | Rejection funnel recorded per run | The diagnostic that found the bias bug, now permanent |
| Jul 24 | Causality tests run on real ES data | 188 -> 203 tests; invariant is 'no signal created', not 'nothing changes' |
| Jul 24 | Every fill pays half-spread + slippage | Exit leg previously paid no spread; round turn now $51.25/contract on ES |
| Jul 24 | Manual closes pay costs | SESSION_END / circuit-breaker / backtest-end exits were free, 19% of exits |
| Jul 24 | gross_pnl and costs recorded per trade | 'costs ate the edge' is now measured, not inferred |
| Jul 24 | P&L attributed by exit reason | Revealed SESSION_END exits are profitable, not the leak |
| Jul 24 | 2023 screening span + --span flag | Screen in ~6 min/cell instead of ~21; adversarial regime |
| Jul 24 | 203 -> 218 tests (cost model, overrides) | Cost identity gross - costs == net asserted on every exit path |
| Jul 24 | Nearest FVG+OB overlap, not the first found | Flagship setup was using the stalest zone in the window; 102pt stop vs 17pt |
| Jul 24 | realized_r is signed | A full stop-out reported +1.0R, so Avg R:R could never go negative |
| Jul 24 | OTE gate respects the retracement's direction | Was abs()-based; measured +9 points of return once fixed |
| Jul 24 | invert_bias and allowed_directions params | Localised the anti-edge to longs at z = -3.82 |
| Jul 24 | regimes.py rebuilt as ex-ante attribution | Old week presets were hindsight-picked and 3 of 4 sat in the holdout |
| Jul 24 | backtest/intrabar.py — MFE/MAE on 1m bars | Median MFE 0.70R vs 1.59R target; killed the wide-stop hypothesis |
| Jul 24 | Cells carry a hypothesis into the store | A recorded result now says why it was run, not just what it scored |
| Jul 24 | Volume-derived contract roll | Replaces the 7-entry table; matches CME's customary roll dates exactly |
| Jul 24 | Contracts ordered by last observed bar | No symbol parsing, so ESM6's Juneteenth expiry and 1-digit years are moot |
| Jul 24 | session_day() on naive ET wall-clock | Kills the phantom Saturday session at each spring-forward |
| Jul 24 | Non-positive price guard in the DBN loader | Catches UDS spreads whose symbols carry no "-" |
| Jul 24 | main.py validate-data | Checks a Databento file's integrity and calendar before backtesting |
| Jul 24 | Trades entered after a session gap counted | Measures how much the FVG/displacement gap concern actually matters |

---

## Future Improvements (TODO)

- **OTE-refined FVG entry pricing** — Currently FVG+OTE entries use current market price. Should enter at the OTE sweet spot (70.5% fib) or FVG CE (50% midpoint) when FVG and OTE zone overlap. Would give tighter entries with better risk/reward.
- **Precompute PDH/PDL per session day** — `smc.previous_high_low` is **27% of every
  entry bar** and throws away 99.9% of what it computes: it resamples the window to 1D
  and 1W on every bar, then `smc_adapter.detect_previous_high_low` reads only eight
  scalars off the last row. Those scalars change once a day and are recomputed ~96
  times a day. Result-neutral, ~40 lines, **1.37x on every backtest** — more than the
  single-pass sweep refactor would buy at current sweep sizes.
- **Skip `recent_entry_candles` in backtests** — it is an `.iterrows()` over 20 rows
  per bar, consumed only by `ai/prompt.py`. Free 2%.
- **The entry lookback is set by file size, not by strategy** — `get_windowed_data`
  picks 200/500/1000 bars from `len(all_timeframes["entry"])`, i.e. the length of the
  whole file. The 5-year file always lands on 1000. It is a real strategy parameter
  being chosen by accident, and shorter windows are ~2x faster; sweep it as
  `entry_lookback` 200/500/1000 rather than leaving it implicit.
- **Route `CONFLUENCE_WEIGHTS` through `params`** before making weights sweepable.
  It is a dict bound by value at import (`ict/confluence.py`), so mutating it to sweep
  weights would be process-global and `params.overrides` would not restore it — a leak
  that is invisible under one-cell-per-process and corrupting under anything else.
- **Add engine regression coverage** — 218 tests and none exercise `run_backtest` or
  `_run_backtest_inner`. The fill / session-end / circuit-breaker ordering is
  load-bearing and unguarded, which is where the cost bugs lived.
- **Find out why the win rate is 13%** — see experiment 16. Stop at 2.4x ATR is reasonable; the 5.6x ATR target is rarely reached. Test a shorter target, a wider stop, or accept the entry has no edge on 15m ES.
- **Add a research switch for the circuit breaker** — latching at 10% hides everything after the first drawdown, so a multi-year run reports two months.
- **Align live and backtest swing lengths** — `SMC_SWING_LENGTH` uses bias=50, `BACKTEST_SMC_SWING_LENGTH` uses bias=10, so a backtest does not validate the signals live will produce. Aligning needs `HTF_WARMUP_DAYS` above 145 (101 daily bars for swing_length=50); it is 90 today.
- **Guard detectors across data gaps** — measured on real data and it looks minor: only 1 of 17 trades entered after a session break, and front-month ES has near-complete minute coverage (42 gaps of 1-60 minutes in a year). Revisit only if the trade count grows.
- **Regime detection** — Strategy excels in trending markets but struggles in choppy conditions. Add a volatility/regime filter to reduce position size or skip trades during ranging periods.
- **Calibrate spread and slippage against real quotes** — `SPREAD_POINTS`, `SLIPPAGE_POINTS` and `COMMISSION_PER_CONTRACT` are now applied but set from published figures, not measured. One week of Databento `tbbo` (every trade plus the quote before it) would give the spread actually paid, by session.
- **Trade management tuning** — Test partial close at 25% instead of 50% at 1R to preserve more upside on winners while still getting breakeven protection.
- **Multi-asset testing** — Run BTC-USD backtests with the new bias system and per-asset SL multipliers to validate crypto performance.
- **Raise circuit breaker threshold** — Best config hits 10.9% max DD, exceeding the 10% circuit breaker. Consider 12-15% threshold for aggressive configs.
- **Multi-timeframe entry (5min + 15min combined)** — Currently backtests run on a single entry timeframe. Test running both 5min and 15min simultaneously — 15min for higher-quality setups with better WR, 5min for more frequent entries. Could capture setups that only appear on one timeframe while diversifying signal sources.
