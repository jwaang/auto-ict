# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

ICT Paper Trading Simulator — applies Inner Circle Trader (ICT) methodology to paper trade MES (Micro E-mini S&P 500) futures via Interactive Brokers. Fetches OHLC data from IBKR, algorithmically detects ICT concepts (FVGs, OBs, market structure, etc.), makes trade decisions (rule-based or Claude AI), places bracket orders (entry + SL + TP) on IBKR paper trading account, and logs everything for re-analysis. Includes a walk-forward backtesting engine with no look-ahead bias.

**Paper trading only — uses IBKR paper account. No real money at risk.**

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

# Walk-forward threshold optimization
py main.py optimize data.csv --ticker ES --entry-tf 15min
py main.py optimize data.csv --thresholds 30,40,50,60,70,80 --start 2026-01-01

# Run tests
py -m pytest tests/ -v              # all 55 tests
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
| `backtest/` | `optimize.py` | Walk-forward confluence threshold optimization (train/test split) |
| `journal/` | `logger.py` | JSON trade log with ICT context snapshots and IBKR order IDs |
| `tests/` | `test_no_lookahead.py`, `test_trading.py`, `test_data_historical.py` | 55 regression tests (causality, trading, data) |

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

When `--start` is provided, 90 extra days of data are loaded before the start date for HTF warmup (daily/4H need enough bars for swing detection). The engine uses a `trade_start` parameter to only open trades within the requested date range.

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

1. **HTF bias required** — daily must be bullish or bearish (falls back to 4H swing bias if daily is neutral)
2. **Kill zone gate** (non-crypto only) — entries only during London (2-5 AM ET), NY (7-11 AM ET), or Asian (7-10 PM ET)
3. **Dead zone block** — no entries during NY lunch (11 AM - 1 PM ET)
4. **Confluence >= 60**
5. **Actionable ICT levels** — needs FVG+OB overlap or standalone FVG aligned with bias (standalone OB filtered out for futures)
6. **Minimum 2:1 R:R**
7. **Session-end close** (non-crypto) — all positions force-closed at 4 PM ET (day trades only, no overnight holds). SL/TP fills are checked BEFORE session-end so real fills take priority over synthetic close.

Crypto tickers (detected by `is_crypto()` or `--ticker BTC-USD`) bypass kill zone/dead zone/session-end rules.

## Risk Management

Enforced in `trading/risk.py`:
- Max 1% account per trade, minimum 2:1 R:R
- Max 3 concurrent positions
- SL bounds: 0.1-5% from entry (stocks/crypto) or 2-50 points (futures)
- Per-asset SL ATR multiplier (`config.SL_ATR_MULTIPLIER`): ES=0.5, BTC=1.5, etc.
- 10% drawdown from peak = circuit breaker (latching — halts all trading, force-closes open positions)
- Position sizing: `risk_amount / sl_distance` (stocks/crypto), `floor(risk_amount / (sl_points * point_value))` integer contracts (futures)
- Configurable spread/slippage modeling (`config.SPREAD_POINTS`, `config.SLIPPAGE_POINTS`) — defaults to 0, set nonzero for realistic backtests

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
- `BACKTESTING-FINDINGS.md` — Documented backtest results and analysis across ES and BTC

## Data Sources

| Source | Used For | Auth |
|--------|----------|------|
| Interactive Brokers | Live OHLC + order execution + historical download | Local TCP (TWS/Gateway) |
| Databento CSV | Historical backtesting (1m OHLCV) | Downloaded files |

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

**Databento CSV**: columns `ts_event, rtype, publisher_id, instrument_id, open, high, low, close, volume, symbol`. The loader handles contract stitching (ES roll dates), spread symbol filtering, and resampling.

**IBKR CSV** (from `download-history`): columns `timestamp, open, high, low, close, volume`. Timestamps are timezone-aware (CT offsets), converted to UTC on load. The download anchors at 5 PM ET session close to capture full 23-hour trading days.
