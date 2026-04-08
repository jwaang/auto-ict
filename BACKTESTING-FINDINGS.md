# ICT Backtesting Findings

## Overview

Walk-forward backtesting of the ICT (Inner Circle Trader) strategy on ES futures (E-mini S&P 500) using 1-minute OHLCV data from Databento, resampled to multiple timeframes. All results use the causal (no look-ahead bias) detection engine.

**Dataset:** `glbx-mdp3-20250407-20260406.ohlcv-1m.csv` — 352K 1-minute bars, Apr 2025 - Apr 2026, continuous front-month contract (ESM5 -> ESU5 -> ESZ5 -> ESH6).

**Starting balance:** $100,000. Risk per trade: 1%. Minimum confluence score: 60/100. Minimum R:R: 2:1.

---

## Evolution of Results

The backtesting engine went through several iterations as look-ahead bias was identified and removed. Each fix produced more realistic (and different) results.

### Version 1: Original SMC Library (centered window + no causal shift)

| Metric | 3-Month (Apr-Jul) | Full Year |
|--------|-------------------|-----------|
| Net P&L | +$9,967 (+10.0%) | +$157,572 (+157.6%) |
| Trades | 16 | 87 |
| Win Rate | 50.0% | 49.4% |
| Profit Factor | 2.20 | 2.54 |
| Max Drawdown | 4.0% | 12.4% |

**Bias present:** `swing_highs_lows()` used a centered window (`shift(-(swing_length // 2))`) that looked forward by `swing_length // 2` bars. `fvg()` used `shift(-1)` to detect gaps 1 bar before they were knowable. All downstream functions (BOS/CHoCH, OB, liquidity) inherited biased swing data. These results are **invalid** and should not be trusted.

### Version 2: Confirm-bars swing detection + FVG causal shift

| Metric | 3-Month (Apr-Jul) |
|--------|-------------------|
| Net P&L | +$13,584 (+13.6%) |
| Trades | 13 |
| Win Rate | 53.8% |
| Profit Factor | 3.13 |
| Max Drawdown | 3.0% |

**Fixes applied:**
- `swing_highs_lows()` replaced with confirm-bars approach: candidate must be the extreme in the lookback window, confirmed by `swing_length` subsequent bars all being less extreme
- `fvg()` output shifted forward by 1 bar so signal appears after the confirming (3rd) candle closes
- Swing signals placed at candidate bar index initially

**Remaining bias:** Swing signals were placed at the candidate bar (where the price level is) rather than the confirmation bar (where the swing becomes knowable). BOS/CHoCH were backdated to `last_positions[-2]` (an earlier swing index) when the 4th swing made the pattern detectable. Boundary swing injection at bar 0 fabricated structure context.

### Version 3: Full causal — confirmation bar placement + no boundary injection

**Fixes applied:**
- Swing signals emitted at confirmation bar `i`, not candidate bar `i - confirm_bars`
- `Level` column stores the candidate's actual price (not OHLC at the signal index)
- `ob()` updated to use `swing_lv[]` for price comparisons instead of `_high[swing_index]`
- BOS/CHoCH emitted at bar `i` (where the 4th swing makes the pattern knowable), not backdated to `last_positions[-2]`
- Boundary swing injection at bar 0 and last bar removed entirely
- Minimum bar requirements per timeframe made proportional (bias: 5, swing: 10, setup: 20, entry: 30)

This is the current production version. All 55 regression tests pass. No known look-ahead bias remains.

---

## ES Futures Results (Version 2 — 15min entry)

These were the last complete ES runs before the BOS/CHoCH and boundary fixes. Version 3 results pending re-run.

### 3-Month Run (Apr 7 - Jul 1, 2025)

```
Starting Balance: $100,000.00
Final Balance:    $113,584.21
Net P&L:          $13,584.21 (+13.6%)
Max Drawdown:     3.0%
Profit Factor:    3.13

Total Trades:     13
Win Rate:         53.8%
Wins / Losses:    8 / 4 (note: changed from 7/6 after boundary fix pending)
Avg Win:          $2,850.31
Avg Loss:         $1,061.33
Best Trade:       $3,238.99
Worst Trade:      $-1,112.90
Avg R:R:          1.94
Max Win Streak:   3
Max Loss Streak:  3
```

**Monthly breakdown:**
| Month | P&L |
|-------|-----|
| May 2025 | +$2,101 |
| Jun 2025 | +$9,112 |
| Jul 2025 | +$2,372 |

### Full Year Run (Apr 7, 2025 - Apr 6, 2026) — Version 1 (biased, for reference only)

```
Net P&L:          $157,571.64 (+157.6%)  ← INFLATED BY LOOK-AHEAD BIAS
Max Drawdown:     12.4%
Profit Factor:    2.54
Total Trades:     87
Win Rate:         49.4%
```

**Monthly breakdown:**
| Month | P&L | Notes |
|-------|-----|-------|
| May 2025 | +$5,384 | |
| Jun 2025 | +$4,777 | |
| Jul 2025 | +$61,087 | Best month — large trending moves |
| Aug 2025 | +$27,214 | |
| Sep 2025 | +$36,017 | |
| Oct 2025 | +$37,457 | |
| Nov 2025 | +$13,430 | |
| Jan 2026 | +$2,712 | Dec had no trades |
| Feb 2026 | -$27,653 | Worst month — 11-loss streak |
| Mar 2026 | -$2,854 | |

---

## ES Futures: 5-Minute vs 15-Minute Entry Comparison

Tested on Apr 7 - Jun 1, 2025 (Version 2).

| Metric | 5min Entry | 15min Entry |
|--------|-----------|-------------|
| Entry bars | 10,692 | 5,489 |
| Bars processed | 3,398 | 1,323 |
| **Trades** | 12 | 13 |
| **Win Rate** | **66.7%** | 53.8% |
| **Profit Factor** | **3.57** | 3.13 |
| Net P&L | +$11,197 (+11.2%) | +$13,584 (+13.6%) |
| Max Drawdown | 3.0% | 3.0% |
| Avg Win | $1,944 | $2,850 |
| Avg Loss | $1,089 | $1,061 |
| Runtime | 679s (~11 min) | 109s (~2 min) |
| No-trade rejections | **817** | 21 |

### Key Observations

1. **5min has higher win rate (66.7% vs 53.8%) and profit factor (3.57 vs 3.13)** but fewer total trades and lower total P&L. The higher granularity provides better entry timing but tighter ICT levels produce smaller wins (avg $1,944 vs $2,850).

2. **5min rejects far more setups** — 817 no-trade decisions vs 21. At 5min resolution, more FVGs and OBs form but they're noisier, so many pass confluence scoring but fail SL/TP validation (R:R too low, SL too tight/wide).

3. **5min takes ~6x longer to run** due to 3x more bars processed and more ICT analysis calls per bar.

4. **Tradeoff:** 5min is better for precision and win rate; 15min is better for capturing larger moves and total P&L. For production use, 15min is more practical (faster, larger average wins, similar drawdown).

---

## BTC Results

Dataset: `xnas-itch-20250408-20260407.ohlcv-1m.csv` — 76K bars, BTC on NASDAQ, full year.

### BTC: 5-Minute vs 15-Minute Entry

| Metric | BTC 5min | BTC 15min |
|--------|---------|-----------|
| Entry bars | 21,715 | 8,870 |
| **Trades** | 11 | 34 |
| **Win Rate** | **0.0%** | 26.5% |
| **Profit Factor** | 0.0 | **2.98** |
| **Net P&L** | **-$10,577 (-10.6%)** | **+$72,104 (+72.1%)** |
| Max Drawdown | 10.6% | 10.6% |
| Avg Win | $0 | $12,054 |
| Avg Loss | $962 | $1,455 |
| Best Trade | -$922 (all losses) | +$30,611 (24.6R) |
| Runtime | 1,918s (~32 min) | 437s (~7 min) |

### BTC 5min — Complete Failure

```
Net P&L:          -$10,576.86 (-10.6%)
Total Trades:     11
Win Rate:         0.0%  ← Every single trade hit SL
Wins / Losses:    0 / 11
Max Loss Streak:  11
```

**Setup breakdown (all losers):**
| Setup | Trades | WR | P&L |
|-------|--------|-----|-----|
| Order Block | 8 | 0% | -$7,577 |
| FVG+OB overlap | 3 | 0% | -$3,000 |

All 11 trades were LONGs that hit SL. The 5-minute FVG/OB zones on BTC are so narrow that normal volatility noise sweeps through them before the directional move develops. **5min entry is unsuitable for BTC.**

### BTC 15min — Lottery-Ticket Profile

```
Net P&L:          $72,103.78 (+72.1%)
Total Trades:     34
Win Rate:         26.5%
Avg Win:          $12,054.27
Avg Loss:         $1,455.39
Best Trade:       $30,610.98 (24.6R)
Max Win Streak:   6
Max Loss Streak:  11
```

**Monthly breakdown:**
| Month | P&L |
|-------|-----|
| Jun 2025 | -$6,870 |
| Jul 2025 | +$40,548 |
| Aug 2025 | +$38,426 |

**Setup breakdown:**
| Setup | Trades | WR | P&L |
|-------|--------|-----|-----|
| Fair Value Gap | 12 | 25% | +$53,017 |
| Order Block | 13 | 46% | +$31,570 |
| FVG+OB overlap | 9 | 0% | -$12,483 |

Three FVG trades in July hit +$22K, +$30K, and +$14K — carrying the entire year. The 24.6R trade occurred because the SL was very tight ($0.12 from a FVG edge) while the TP was a distant liquidity target at $53.15. No profit scaling or trailing stop was used — the system is fixed SL/TP only.

### BTC vs ES — Different Character

BTC produces a **lottery-ticket profile**: very low win rate (26.5%) but massive winners that more than compensate. The strategy functions as a trend-follower on BTC — most entries fail, but the ones that catch a multi-day trend produce outsized returns.

ES produces a **consistent grinder profile**: moderate win rate (50-67%) with smaller but steady wins. FVG+OB overlap is the dominant edge on ES.

### Critical Finding: Entry Timeframe Must Match Asset Volatility

| Asset | 5min Entry | 15min Entry | Verdict |
|-------|-----------|-------------|---------|
| **ES** | 66.7% WR, PF 3.57 | 53.8% WR, PF 3.13 | Both work; 5min better WR, 15min better P&L |
| **BTC** | **0.0% WR, PF 0.0** | 26.5% WR, PF 2.98 | **5min catastrophic; 15min only** |

5-minute ICT levels are too tight for BTC's volatility — SLs placed at FVG/OB edges get swept by normal noise before the move develops. ES has lower intrabar volatility relative to its ICT zone sizes, so 5min zones survive. **Per-asset minimum entry timeframe is essential.**

---

## ICT Setup Type Performance

### ES Futures (across all backtests)

| Setup Type | Trades | Win Rate | Net P&L | Assessment |
|------------|--------|----------|---------|------------|
| **FVG+OB overlap** | 15-31 | **53-75%** | **+$9,761 to +$67,800** | Best overall — highest confluence signal, most consistent |
| **Fair Value Gap** | 12-20 | **25-60%** | +$53,017 to +$94,317 | High P&L when it works, variable win rate |
| **Order Block** | 1-36 | **0-50%** | -$4,546 to +$31,570 | Weakest standalone — loses money without additional confluence |

### BTC (full year, 15min)

| Setup Type | Trades | Win Rate | Net P&L | Assessment |
|------------|--------|----------|---------|------------|
| **Fair Value Gap** | 12 | 25% | **+$53,017** | Low WR but massive outlier wins |
| **Order Block** | 13 | **46%** | +$31,570 | Best WR on BTC |
| **FVG+OB overlap** | 9 | **0%** | -$12,483 | All losers — overlap zones too tight for BTC volatility |

### Cross-Asset Observations

1. **FVG+OB overlap is the best signal on ES but the worst on BTC.** The overlap creates tight entry zones that work well on ES (lower volatility, tighter ranges) but get stopped out on BTC (higher volatility, wider swings).

2. **Standalone Order Blocks underperform on ES** (33% WR in the full-year run, -$4,546) but work on BTC (46% WR, +$31,570). OBs may need different SL sizing per asset class.

3. **Fair Value Gaps are the high-conviction setup on BTC** despite low win rate, because BTC trends produce massive FVG-to-FVG runs when they work.

---

## Known Issues and Gaps

### Currently Not Implemented

1. **Kill zone hard filter** — Added in latest version. Trades on ES are now restricted to London (2-5 AM ET), NY (7-11 AM ET), and Asian (7-10 PM ET) sessions only. NY lunch dead zone (11 AM - 1 PM ET) blocks entries.

2. **No trade management** — Current system is set-and-forget with fixed SL/TP. No trailing stops, no partial profit taking, no moving SL to breakeven after 1R. This explains the extreme R:R variance (some trades achieve 24.6R because TP is a distant liquidity target with a tight SL).

3. **No Power of 3 / Judas Swing detection** — The research doc describes the Accumulation-Manipulation-Distribution pattern as fundamental to ICT. The backtest doesn't identify the daily Judas Swing or use it to filter entries.

4. **No Breaker Block or Mitigation Block detection** — These are OB variants with higher/lower probability. Currently all OBs are treated equally.

5. **No IFVG (Inversion FVG)** — FVGs that get completely broken through and flip role are not tracked.

6. **TP targeting is naive** — `_find_take_profit()` grabs the first liquidity zone with R:R >= 2, which can be very far. Should prioritize nearest valid target for realistic fills.

7. **No spread/slippage modeling** — All entries and exits at exact SL/TP prices. Research doc recommends 2-3 pip spread assumptions.

8. **Circuit breaker not enforced globally** — The 10% drawdown circuit breaker is checked per-trade but doesn't halt all trading when triggered. The full-year ES run exceeded 12.4% drawdown.

### Potential Improvements (Not Yet Tested)

- Filter out standalone OB entries on ES (only trade FVG+OB overlap and standalone FVG)
- Add partial profit taking: close 50% at 1:1 R:R, trail remainder
- Tighten TP to nearest liquidity target instead of any valid target
- Add Silver Bullet window bonus (10-11 AM ET) — weight entries during this hour higher
- Per-asset SL multiplier (BTC needs wider SL than ES)
- Walk-forward optimization of confluence threshold (currently fixed at 60)

---

## Methodology Notes

### Multi-Timeframe Hierarchy

| Label | Timeframe | Purpose | Source |
|-------|-----------|---------|--------|
| bias | Daily | HTF market direction | 1m resampled to 1D |
| swing | 4H | Intermediate structure (bias fallback) | 1m resampled to 4H |
| setup | 1H | Setup identification (FVGs, OBs) | 1m resampled to 1H |
| entry | Configurable (1m/5m/15m) | Entry signals, trade execution | 1m resampled |

### Confluence Scoring (0-100)

| Factor | Weight | Description |
|--------|--------|-------------|
| HTF bias aligned | 15 | Entry direction matches daily bias |
| FVG+OB overlap | 12 | Strongest confluence — imbalance + institutional zone |
| FVG present | 10 | Fair value gap exists on entry TF |
| OB present | 10 | Order block exists on entry TF |
| Liquidity sweep | 10 | Stop hunt detected before entry |
| OTE zone | 10 | Price in 61.8-79% Fibonacci retracement |
| PDH/PDL target | 8 | Near previous day/week high/low |
| Displacement | 8 | Impulsive candle (body > 2x ATR) |
| MSS present | 7 | Market Structure Shift (CHoCH + displacement) |
| Kill zone | 5 | In London/NY/Asian session |
| Silver Bullet | 5 | In 1-hour high-probability window |
| Premium/Discount | 5 | Buy in discount, sell in premium |
| CE at OB | 5 | FVG midpoint aligns with OB midpoint |

Minimum score to trade: 60/100.

### Look-Ahead Bias Protections

1. **Bar-close timestamps** — Resampled bars are labeled by their close time, not open. A 1H bar covering 10:00-10:59 is stamped 11:00.
2. **Confirm-bars swing detection** — Swings require `swing_length` subsequent bars to confirm. No centered window.
3. **FVG causal shift** — FVG signals shifted forward 1 bar so they appear after the 3rd candle closes.
4. **BOS/CHoCH at discovery time** — Structure breaks emitted when the 4th swing makes the pattern knowable, not backdated.
5. **No boundary injection** — No fabricated swings at first/last bars.
6. **Point-in-time windowing** — `get_windowed_data()` only includes completed bars at each analysis point.
7. **55 regression tests** verify all causality invariants.
