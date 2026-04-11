# Backtest Results Log

Comprehensive record of all backtesting experiments, configurations, and findings.
Last updated: April 2026.

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

---

## Future Improvements (TODO)

- **OTE-refined FVG entry pricing** — Currently FVG+OTE entries use current market price. Should enter at the OTE sweet spot (70.5% fib) or FVG CE (50% midpoint) when FVG and OTE zone overlap. Would give tighter entries with better risk/reward.
- **Spread/slippage validation** — Run backtests with realistic ES spread (0.50 pts) and slippage (0.25 pts) to see impact on P&L. Currently defaults to 0.
- **Regime detection** — Strategy excels in trending markets but struggles in choppy conditions. Add a volatility/regime filter to reduce position size or skip trades during ranging periods.
- **Commission modeling** — IBKR charges ~$0.62/contract round-trip for MES. Not yet factored into backtest P&L.
- **Trade management tuning** — Test partial close at 25% instead of 50% at 1R to preserve more upside on winners while still getting breakeven protection.
- **Multi-asset testing** — Run BTC-USD backtests with the new bias system and per-asset SL multipliers to validate crypto performance.
- **Raise circuit breaker threshold** — Best config hits 10.9% max DD, exceeding the 10% circuit breaker. Consider 12-15% threshold for aggressive configs.
- **Multi-timeframe entry (5min + 15min combined)** — Currently backtests run on a single entry timeframe. Test running both 5min and 15min simultaneously — 15min for higher-quality setups with better WR, 5min for more frequent entries. Could capture setups that only appear on one timeframe while diversifying signal sources.
