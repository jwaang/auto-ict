# Backtest Results Log

Record of backtesting experiments, configurations, and findings.
Last updated: July 2026.

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
