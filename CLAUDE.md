# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

ICT Paper Trading Simulator — applies Inner Circle Trader (ICT) methodology to paper trade MES (Micro E-mini S&P 500) futures via Interactive Brokers. Fetches OHLC data from IBKR, algorithmically detects ICT concepts (FVGs, OBs, market structure, etc.), makes trade decisions (rule-based or Claude AI), places bracket orders (entry + SL + TP) on IBKR paper trading account, and logs everything for re-analysis. Includes a walk-forward backtesting engine with no look-ahead bias.

**Paper trading only — uses IBKR paper account. No real money at risk.**

## Setup

```bash
py -m pip install -r requirements.txt
```

Target Python 3.12+. Use `snake_case` for functions/variables/modules, `PascalCase` for classes, `UPPER_CASE` for constants in `config.py`. Commit messages: imperative mood with prefix (e.g. `feat: add conditional entry validation`, `fix: handle empty candles`).

## Commands

```bash
# Start continuous live trading (streams bars, auto-analyzes, places orders)
py main.py live

# One-shot ICT analysis on MES via IBKR
py main.py analyze MES

# Check open IBKR positions and orders
py main.py check-positions

# Show trading statistics / journal
py main.py stats
py main.py journal --limit 20

# Download historical 1m data from IBKR (requires TWS/Gateway running)
py main.py download-history                          # 90 days ES, saves to historical/
py main.py download-history --symbol MES --days 30
py main.py download-history --symbol ES --days 90 --save historical/ES-90d.csv

# Experiment harness — run a named sweep, then rank everything recorded so far
py main.py sweep smoke historical/ES-5y/glbx-mdp3-20210724-20260723.ohlcv-1m.dbn.zst
py main.py sweep bias historical/ES-5y/glbx-mdp3-20210724-20260723.ohlcv-1m.dbn.zst
py main.py sweep-report --top 20

# Check a dataset before backtesting on it (integrity, session calendar, rolls)
py main.py validate-data historical/ES-5y/glbx-mdp3-20210724-20260723.ohlcv-1m.dbn.zst

# Backtest on historical 1-minute OHLCV data
py main.py backtest path/to/ohlcv-1m.csv
py main.py backtest data.csv --ticker ES --start 2025-04-07 --end 2025-07-01
py main.py backtest data.csv --ticker BTC-USD --entry-tf 15min  # crypto: no kill zone/session-end rules
py main.py backtest data.csv --entry-tf 5min                    # default: 15min
py main.py backtest data.csv --min-score 50 --balance 50000
py main.py backtest data.csv --strategy ict_2022                # ICT 2022 Model strategy
py main.py backtest data.csv --strategy silver_bullet            # Silver Bullet strategy
py main.py backtest data.csv --strategy default                  # confluence scoring (default)
py main.py backtest data.csv --step 8 --save logs/results.json
py main.py backtest data.csv --regime-test --entry-tf 5min  # quick 4-week regime validation

# Walk-forward threshold optimization
py main.py optimize data.csv --ticker ES --entry-tf 15min
py main.py optimize data.csv --thresholds 30,40,50,60,70,80 --start 2026-01-01

# Run tests
py -m pytest tests/ -v              # all tests
py -m pytest tests/test_no_lookahead.py -v   # causality tests only
py -m pytest tests/test_trading.py -v        # trading module tests only
py -m pytest tests/ -k "test_fvg"            # run tests matching pattern

# Launch Streamlit dashboard
streamlit run ui/app.py
```

## Architecture

### Three Execution Paths

1. **Live Trading (IBKR)** — `main.py live` runs a continuous daemon that connects to IBKR, streams live 15m bars, and triggers ICT analysis each time a bar completes. When signals fire during kill zones, bracket orders (entry + SL + TP) are placed on the IBKR paper account. The daemon also monitors open positions for fills and handles session-end close. One-shot analysis available via `main.py analyze MES`.

2. **Backtesting (Default Strategy)** — `main.py backtest CSV` loads historical 1m data, resamples to all timeframes, walks forward through entry bars running the full ICT detection pipeline with confluence scoring, uses deterministic rule-based decisions, simulates trades with position/risk management.

3. **Backtesting (ICT Strategies)** — `main.py backtest CSV --strategy ict_2022|silver_bullet` bypasses the confluence scoring system entirely. These strategies use only `smc_patched.py` detections (via `smc_adapter.py`) and implement specific ICT setups with temporal sequence detection (sweep → MSS → FVG entry).

### Data Flow

```
Live: live.py streams 15m bars from IBKR
  -> On bar close: ict/confluence.py (runs all ICT detectors across 4 timeframes)
  -> backtest/rules.py (rule-based) OR ai/analyst.py (AI)
  -> trading/risk.py validates (futures-aware)
  -> broker/ibkr.py places bracket order on IBKR paper account
  -> live.py monitors for IBKR fill events + session-end close
  -> journal/logger.py logs everything

Backtest (default): Historical CSV (data/historical.py)
  -> ict/confluence.py (same detection pipeline + scoring)
  -> backtest/rules.py (deterministic)
  -> trading/positions.py simulates fills (with optional trade management)
  -> journal/logger.py logs results

Backtest (strategies): Historical CSV (data/historical.py)
  -> backtest/strategies/{ict_2022,silver_bullet}.py
  -> backtest/strategies/common.py (smc_adapter calls + sequence detection)
  -> trading/positions.py simulates fills
```

### Module Responsibilities

| Module | Key File | Does |
|--------|----------|------|
| `live.py` | `live.py` | Continuous streaming daemon — streams bars, triggers analysis, monitors fills, session-end close |
| `broker/` | `ibkr.py` | IBKR connection, contract management, bracket orders, market data, live bar streaming, historical data download |
| `data/` | `historical.py` | Historical CSV loader (Databento + IBKR formats), contract stitching, resampling |
| `ict/` | `confluence.py`, `smc_patched.py`, `smc_adapter.py` | ICT detection engine — vendored SMC library (bias-free) + adapter + confluence scoring |
| `ict/` | `breaker_blocks.py`, `ifvg.py`, `po3.py` | Advanced detectors: Breaker Blocks, Inversion FVGs, Power of 3 / Judas Swing |
| `ai/` | `analyst.py` | Calls Claude Code CLI (`claude -p --model claude-sonnet-4-20250514`), parses JSON response |
| `trading/` | `risk.py`, `positions.py`, `account.py` | Risk validation (futures-aware), position simulation with trade management, account tracking with circuit breaker |
| `backtest/` | `engine.py`, `rules.py`, `report.py` | Walk-forward backtesting engine with rule-based decisions and analytics |
| `backtest/strategies/` | `ict_2022.py`, `silver_bullet.py`, `common.py` | ICT-specific strategies using temporal sequence detection (sweep → MSS → FVG) |
| `backtest/` | `optimize.py` | Walk-forward confluence threshold optimization (train/test split, parallel) |
| `backtest/` | `experiments.py`, `sweeps.py`, `params.py` | Experiment harness — config matrix runner, named sweeps, per-run parameter overrides |
| `data/` | `validate.py` | Dataset checker: integrity, session calendar, rolls, condition flags |
| `backtest/` | `regimes.py` | Regime-based test presets (4 representative weeks per asset for quick validation) |
| `journal/` | `logger.py` | JSON trade log with ICT context snapshots and IBKR order IDs |
| `tests/` | `test_no_lookahead.py`, `test_trading.py`, `test_smc_patched.py`, etc. | 188 regression tests (causality on synthetic AND real data, trading, SMC detectors, data loading, contract rolls, session days, session alignment) |

### Vendored SMC Library (`ict/smc_patched.py`)

The `smartmoneyconcepts` package (v0.0.27) has critical look-ahead bias in its core functions. We vendor a patched copy at `ict/smc_patched.py` with these fixes:
- `swing_highs_lows()`: Replaced centered window with confirm-bars approach (no future data)
- `fvg()`: Output shifted forward by 1 bar (signal after 3rd candle closes)
- `bos_choch()`: Signals emitted at discovery time, not backdated to earlier swing
- No boundary swing injection at first/last bars

`ict/smc_adapter.py` wraps all calls to the patched library and supports runtime `swing_length` overrides for backtesting. Do not modify `smc_patched.py` — new detectors go in separate modules.

### ICT Detection Engine (`ict/`)

`confluence.py` orchestrates all detectors. The SMC library (via `smc_adapter.py`) handles: swings, BOS/CHoCH, FVGs, order blocks, liquidity, retracements, previous high/low. Custom detectors handle: displacement (`displacement.py`), kill zones (`killzones.py`), Fibonacci/OTE (`fib.py`), ATR (`candles.py`).

Advanced detectors (integrated into both confluence scoring and strategy paths):
- `breaker_blocks.py` — mitigated OB + liquidity sweep = Breaker Block with flipped polarity
- `ifvg.py` — fully mitigated FVG flips role (bullish → bearish IFVG, etc.)
- `po3.py` — Power of 3: Asian session range → Judas Swing detection → distribution phase

The SMC adapter is lazy-imported — setting `USE_SMC_LIBRARY=False` in config falls back to hand-rolled detectors without requiring the `smartmoneyconcepts` package.

### Strategy System (`backtest/strategies/`)

Two concrete ICT strategies bypass the confluence scoring system:

- **ICT 2022 Model** (`ict_2022.py`): Sweep sell/buy-side liquidity → MSS (CHoCH) on entry TF → enter on FVG retracement. Kill zones: London 3-5 AM, NY 7-11 AM ET. Min 1:3 R:R.
- **Silver Bullet** (`silver_bullet.py`): Same sweep→MSS→FVG logic restricted to three 1-hour windows (3-4 AM, 10-11 AM, 2-3 PM ET). Entire sequence must form within the active window. Min 1:2 R:R.

Both share temporal sequence detection (`common.py`), which verifies causal ordering: `sweep_candle_index < choch_candle_index < fvg_candle_index`. The `common.py` module also provides cached SMC detections, entry criteria checklist, stop loss/TP calculation, and inline ATR.

Select via `--strategy ict_2022|silver_bullet|default` CLI flag. The `default` strategy uses the full confluence scoring path unchanged.

## Multi-Timeframe Analysis

| Label | Timeframe | Purpose |
|-------|-----------|---------|
| `bias` | Daily | HTF market structure bias |
| `swing` | 4H | Intermediate structure (bias fallback when daily is neutral) |
| `setup` | 1H | Setup identification (FVGs, OBs) |
| `entry` | Configurable (1m/5m/15m) | Entry signals and trade execution |

For backtesting, all timeframes are resampled from 1m data. Bar timestamps use **bar-close labeling** (a 1H bar covering 10:00-10:59 is stamped 11:00) to prevent look-ahead bias in windowed analysis.

Daily and 4H bars are **session-aligned**: their bins run from the 18:00 ET CME open rather than UTC midnight, so one daily bar covers one trading day (18:00 ET to 17:00 ET) instead of straddling two. The boundary follows ET wall-clock, so it holds across DST. Pass `session_aligned=True` to `resample_ohlcv()`. Hourly and finer bins land on the same edges either way and do not use it.

When `--start` is provided, 90 extra days of data are loaded before the start date for HTF warmup (daily/4H need enough bars for swing detection). The engine uses a `trade_start` parameter to only open trades within the requested date range.

## Experiment Harness (`backtest/`)

Strategy research runs through a config matrix, not by hand-editing constants.

**`params.py` — per-run overrides.** Most constants reach their consumers through
`from config import X`, which binds the value at import time, so rebinding `config.X`
per run does nothing. Consumers that need to be sweepable read
`params.get("name", CONFIG_DEFAULT)` at call time instead, and a runner wraps each
cell in `with params.overrides({...})`. This generalises the pattern
`ict.smc_adapter.set_swing_length_override` already used. It is fork-safe: each
`ProcessPoolExecutor` worker gets its own module globals.

**When adding a sweepable knob, route it through `params.get()` at every site that
reads it.** `MIN_RR_RATIO` is enforced in both `backtest/rules.py` and
`trading/risk.py`; overriding one alone leaves the other vetoing every trade.

Overrides in use: `min_rr_ratio`, `tp_min_r`, `tp_selection`, `tp_fallback_r`,
`futures_min_sl_points`, `futures_max_sl_points`, `drawdown_limit_pct`,
`smc_swing_length`, `bias_factors_used`, `bias_vote_rule`, `bias_min_votes`.

**`experiments.py` — matrix runner and store.** Workers get the data file *path*, not
the frame, and cache it per process; pickling 1.8M rows per cell would cost more than
the backtest. Workers are bounded to `cpu_count - 2`. A failing cell is recorded as a
row with an `error`, never allowed to kill the sweep. Every cell appends one line to
`logs/experiments.jsonl` with its config, the full stats, the rejection funnel,
geometry, direction split and score buckets.

**`sweeps.py` — named, version-controlled matrices.** Sweeps live in git because a
result is only reproducible if the exact cell list is recorded, and the honest reading
of a winner depends on how many configurations were tried. Sweeps are small and
sequential rather than one big factorial, so each answers one question.

Run `sweep smoke` first — macOS spawns workers rather than forking, so an entry-point
problem surfaces in a minute instead of an hour into a real sweep.

**Judging a result.** `sweep-report` ranks by edge over each cell's own benchmark,
because a strategy with a distant target has a low coin-flip win rate and comparing
raw win rates across geometries is meaningless. Cells under 30 trades are unrankable
and under 200 are suggestive only. With many configurations tried, require t > 3
rather than t > 2 (Harvey/Liu/Zhu).

Two things about that benchmark cost a wrong published conclusion each, so read
this before trusting an edge figure.

**Score barrier exits only.** `stop / (stop + target)` is a first-passage result
for two absorbing barriers: it describes a trade ending at its stop or its target
and nothing else. Session-end and circuit-breaker closes end at whatever price is
there, and they skew to small positive scratches, so counting them as wins inflates
every edge. `_geometry` partitions on `exit_reason` and reports `nonbarrier_n` and
`nonbarrier_pnl` separately. Note a forced close being gross-positive is
survivorship — a trade still open at 16:00 is one that was not stopped — not a
reason to prefer a time exit.

**Prefer the measured null to the formula.** `stop / (stop + target)` also assumes
unlimited time, but positions are force-closed at 16:00 ET, and the target is
farther away than the stop, so the cutoff removes target-hits more often. The
formula therefore overstates the benchmark, by ~0.1 points at a 1.7x target and 2
to 3.4 points at 2.5x. `backtest/nullmodel.py` measures it instead: random entries
on the same bars, geometry sampled from the run's own trades, resolved through the
same 1-minute first-touch logic and the same cutoff. Six thousand draws take 0.1
seconds, so every cell carries one and ranking prefers `edge_vs_null`.

Pass `paired=True` for the sharper variant: it reuses each trade's own bar, stop
and target and randomises only direction, so censoring matches exactly and the
result isolates direction skill from timing skill. This matters — real entries
cluster early in the session and are censored 5.8% of the time against 15.8% for
uniform sampling.

**The profitability bar is a number.** Break-even needs
`WR = (1 + cost_share) / (1 + mult)`, so the required edge over a matched null is
+3.5 win-rate points at a 10-point stop, +1.2 at 30 points. Measure a candidate
against that, not against zero.

**Spans.** Screen and select on 2021-07 to 2024-12. 2025 has been seen
diagnostically. 2026-01 to 2026-07 is the untouched holdout — look once, at the end.

**Where this left off.** Sixty-five configurations reached the bar nowhere. The
entry is indistinguishable from random at z +0.11 per concept (n=622 and n=142);
barrier exits and time exits are likewise flat; costs at 11% of R are the binding
constraint. See experiment 26.

The paired null splits the net figure into a **−2.0 point timing component and a
+1.2 point direction component** (n=764, z +0.68, so neither is significant). A
coin flip at the moments this strategy chooses does 2.0 points worse than a coin
flip at random moments, which is what a retracement entry into an FVG buys: entry
against immediate momentum. The bias rule then adds 1.2 points back.

That makes one test worth running before concluding: keep the bias, drop the
retracement requirement, enter at market on the signal bar, and see whether the
timing penalty goes neutral. One cell, ~22 minutes. It will not on its own clear
the +3.5 bar. Beyond it, what remains needs a different instrument, a different
data source such as order flow, or accepting that 15-minute ES is efficient at this
horizon.

## Confluence Scoring (0-100)

| Factor | Weight |
|--------|--------|
| HTF bias aligned | 15 |
| FVG+OB overlap | 12 |
| FVG present | 10 |
| OB present | 10 |
| Liquidity sweep | 10 |
| OTE zone (61.8-79% Fib) | 10 |
| PO3 Judas Swing | 10 |
| PDH/PDL target | 8 |
| Displacement (body > 2x ATR) | 8 |
| Breaker Block | 8 |
| MSS (CHoCH + displacement) | 7 |
| IFVG present | 6 |
| Kill zone | 5 |
| Silver Bullet window | 5 (+5 NY AM bonus) |
| Premium/Discount aligned | 5 |
| CE at OB midpoint | 5 |

Minimum score to trade: 60. Weights defined in `config.CONFLUENCE_WEIGHTS`.

## Backtesting Rules (Default Strategy)

The backtest engine uses deterministic rules (`backtest/rules.py`). The live path (`main.py analyze`) also uses these same rules when `USE_AI_ANALYSIS = False` (current default). Set `True` in `config.py` to re-enable Claude AI decisions.

1. **HTF bias required** — `determine_ict_bias()` combines four factors scored by
   `bias_factors()`: structure direction, liquidity draw, premium/discount, and raid
   status. Default is 3+ aligned, with structure breaking a tie; the rule and the
   factor set are sweepable (`bias_vote_rule`, `bias_min_votes`, `bias_factors_used`).

   Two things to know before touching this. The **raid factor used to abstain on every
   single bar**: it asked whether a side had been swept anywhere in the 200-bar window,
   and with ~16 liquidity zones a bar at ~88% swept the answer was always "both", so
   "3 of 4" was really unanimity. It now compares which side was swept *most recently*.
   And **premium/discount votes bearish ~97% of the time** in a rising market, so as a
   direction vote it is a standing short bias — ICT uses premium/discount to decide
   where to enter inside a bias, not which way to trade. Drop it from the vote with
   `bias_factors_used`. Before these were understood, the function returned a
   directional bias on ~1% of bars and never once returned bullish across 2025.
2. **Kill zone gate** (configurable via `ENFORCE_KILL_ZONES`, default OFF) — when enabled, entries only during London (2-5 AM ET), NY (7-11 AM ET), or Asian (7-10 PM ET). Backtesting showed higher P&L with kill zones OFF.
3. **Dead zone block** (only when kill zones enabled) — no entries during NY lunch (11 AM - 1 PM ET)
4. **Confluence >= 60**
5. **Actionable ICT levels** — needs FVG+OB overlap or FVG+OTE (standalone FVG requires OTE zone for futures; standalone OB filtered out for futures)
6. **R:R veto** — `min_rr_ratio` (default 2.0) rejects a setup whose target is too
   close. It never moves a target. ICT sets the target from liquidity and lets R:R fall
   out, so `_find_take_profit` picks a liquidity level (`tp_min_r`, `tp_selection`) and
   only falls back to a fixed multiple when `tp_fallback_r` is set — with
   `tp_fallback_r: None` a setup with no liquidity to aim at is simply skipped. The
   default 3.0 fallback accounted for 88 of 95 trades in a real run, so the strategy
   was mostly targeting a multiple of its own stop.
7. **Session-end close** (non-crypto) — all positions force-closed during the 4-5 PM ET hour (day trades only, no overnight holds). The check is bounded to that hour; an unbounded `hour >= 16` would also fire all evening and close trades one bar after entry. SL/TP fills are checked BEFORE session-end so real fills take priority over synthetic close.

Crypto tickers (detected by `is_crypto()` or `--ticker BTC-USD`) bypass kill zone/dead zone/session-end rules.

## Risk Management

Enforced in `trading/risk.py`:
- Max 1% account per trade, minimum 2:1 R:R
- Max 3 concurrent positions
- SL bounds: 0.1-5% from entry (stocks/crypto) or 2-50 points (futures)
- Per-asset SL ATR multiplier (`config.SL_ATR_MULTIPLIER`): ES=0.5, BTC=1.5, etc.
- 10% drawdown from peak = circuit breaker (latching — halts all trading, force-closes open positions)
- Position sizing: `risk_amount / sl_distance` (stocks/crypto), `floor(risk_amount / (sl_points * point_value))` whole contracts (futures). Point values live in `config.POINT_VALUES` (ES=$50, MES=$5). A stop too wide to afford one contract opens no position — `open_position()` returns `None` and the engine counts it as `unaffordable_skips`.
- Trading costs are on by default: `SPREAD_POINTS = 0.50`, `SLIPPAGE_POINTS = 0.25`, `COMMISSION_PER_CONTRACT = 1.25`. **Every fill** — entry, SL, TP, and manual closes — pays `SPREAD_POINTS/2 + SLIPPAGE_POINTS` against the position, so a round turn costs 1.00 point plus commission ($51.25/contract on ES). Set them to 0 to compare against gross.
- Each trade records `gross_pnl` and `costs`, and `gross_pnl - costs == pnl_dollars` holds by construction. Do not reintroduce a path that closes a position without going through `_apply_slippage` — session-end closes used to bypass it, making 19% of exits free, and because only net P&L was stored nobody could see it.
- Cost drag as a share of R is `~1.02 / stop_points` and is **independent of position size**, since commission, spread and slippage all scale with contracts exactly as risk does. At a 10-point ES stop that is ~10% of R, which is the binding constraint on any high-frequency configuration.
- Max drawdown is marked to market every bar (`Account.mark_equity`), so it includes open positions. The circuit breaker reads the same figure.

## Trade Management

When `TRADE_MANAGEMENT_ENABLED = True` in config (default: False):
- **Stage 0** (initial): When price reaches 1R profit → partial close 50%, move SL to breakeven (entry price)
- **Stage 1** (trailing): Trail SL behind swing structure until SL hit or session end
- Positions with a single TP level use the legacy binary SL/TP check for backward compatibility

## Trading Rules

- **Stocks and futures (ES, AAPL, etc.):** Day trades only. All positions closed by 4 PM ET. Never hold overnight.
- **Crypto (BTC-USD, etc.):** Can hold swing trades. Positions stay open until SL/TP hit.

## Key Files

- `config.py` — All constants: risk %, ATR params, kill zone times, confluence weights, swing lengths, spread/slippage, trade management, per-asset SL multipliers
- `ict/smc_patched.py` — Vendored + patched SMC library (no look-ahead bias). Do not modify.
- `docs/ICT_Trading_Strategies_Combined_Research.md` — ICT methodology reference (2022 Model, Silver Bullet, Power of 3, etc.)
- `logs/trades.json` — Trade journal (append-only)
- `logs/backtest_trades.csv` — Trade log CSV with reasoning, concepts, bias, and outcome (auto-generated by backtests for manual review)
- `BACKTESTING-FINDINGS.md` — Documented backtest results and analysis across ES and BTC
- `docs/BACKTEST-RESULTS-LOG.md` — Comprehensive log of all backtest experiments with results and configuration history

## Data Sources

| Source | Used For | Auth |
|--------|----------|------|
| Interactive Brokers | Live OHLC + order execution + historical download | Local TCP (TWS/Gateway) |
| Databento DBN or CSV | Historical backtesting (1m OHLCV) | Downloaded files |

The `data/historical.py` loader auto-detects CSV format: Databento (has `ts_event`/`symbol` columns, needs contract stitching) vs IBKR/simple (has `timestamp` directly, single continuous series).

## IBKR Setup

1. Install TWS or IB Gateway, log in with Paper Trading mode
2. Enable API: Edit > Global Config > API > Settings > Enable ActiveX and Socket Clients
3. Port: 7497 (TWS paper) or 4002 (Gateway paper)
4. Subscribe to CME Real-Time market data (non-professional, ~$1-5/mo)
5. No API keys needed — `ib_insync` connects via local TCP socket

## MES Contract Details

- Symbol: MES on CME/GLOBEX (Micro E-mini S&P 500)
- Point value: $5.00/point, tick size: 0.25 ($1.25/tick)
- Trading hours: Sun 5PM CT - Fri 4PM CT, daily halt 4-5 PM CT
- Contract rolls quarterly (Mar/Jun/Sep/Dec) — auto-resolved via `qualifyContracts()`
- Integer contract quantities only

## Ticker Format

Futures use base symbol (e.g. "MES", "ES"). The `is_futures()` helper in `config.py` detects futures symbols. Crypto detection (`is_crypto()` in `killzones.py`) checks for `-USD`, `-USDT` suffixes.

## Historical Data Format

**Databento DBN** (`.dbn`, `.dbn.zst`): the preferred format. Databento meters by uncompressed binary size whatever the encoding, so DBN costs the same as CSV and avoids CSV's 9-decimal price padding. Needs `pip install databento`. `load_continuous_contract()` dispatches on the extension and reads it through `DBNStore.to_df()`.

**Databento CSV**: columns `ts_event, rtype, publisher_id, instrument_id, open, high, low, close, volume, symbol`. The loader handles contract stitching (ES roll dates), spread symbol filtering, and resampling.

Both Databento paths stamp `ts_event` at the **start** of the interval, which is what `resample_ohlcv()` expects — it applies the bar-close shift itself.

**Contract rolls are derived from the data, not a table.** `front_month_schedule()` ranks contracts by their last observed bar (which is their expiry), then picks whichever traded the most volume each session day, latched so a thin day cannot roll backwards. Older contracts are then back-adjusted (Panama) so the ~50-point roll step does not read as an FVG. Measured dates match CME's published customary roll dates exactly.

Do not reintroduce symbol parsing to order contracts. ES uses one-digit year codes (`ESM5` could be 2025 or 2035), CME has begun issuing two-digit ones (`NGN25`), and expiry is not always the third Friday — ESM6 expires 2026-06-18 because 2026-06-19 is Juneteenth.

`session_day()` maps a bar to its CME trading day (18:00 ET open, so the Sunday evening session belongs to Monday). It shifts **naive ET wall-clock**, never a tz-aware timestamp: absolute-time arithmetic drags Sunday-evening bars onto Saturday at every spring-forward and invents a Saturday session that does not exist.

Databento omits minutes with no trade, so a resampled series is not evenly spaced. Detectors that assume contiguous bars (the 3-candle FVG, swing confirm-bars) can pair bars across a weekend or the daily halt. Measured on real front-month ES this is minor — 42 gaps of 1 to 60 minutes in a year — and backtests report `trades_after_break` so the effect stays visible.

A parent-symbol request (`ES.FUT`) returns calendar spreads alongside outrights — 13.8% of records in the 5-year file. The loader drops symbols containing `-` and then drops any bar with a non-positive price, because CME's user-defined spreads do not always join their legs with `-` and spread prices go negative.

**IBKR CSV** (from `download-history`): columns `timestamp, open, high, low, close, volume`. Timestamps are timezone-aware (CT offsets), converted to UTC on load. The download anchors at 5 PM ET session close to capture full 23-hour trading days.
