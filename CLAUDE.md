# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

ICT Paper Trading Simulator — applies Inner Circle Trader (ICT) methodology to paper trade any ticker. Fetches OHLC data, algorithmically detects ICT concepts (FVGs, OBs, market structure, etc.), sends context to Claude for trade decisions, simulates positions with full P&L tracking, and logs everything for re-analysis. Includes a walk-forward backtesting engine with no look-ahead bias.

**No real trades are executed. This is a strategy testing tool.**

## Commands

```bash
# Run ICT analysis on a ticker (fetches data -> detects levels -> AI decision -> paper trade)
py main.py analyze BTC-USD
py main.py analyze AAPL --balance 50000

# Backtest on historical 1-minute OHLCV data
py main.py backtest path/to/ohlcv-1m.csv
py main.py backtest data.csv --ticker ES --start 2025-04-07 --end 2025-07-01
py main.py backtest data.csv --ticker BTC-USD --entry-tf 15min  # crypto: no kill zone/session-end rules
py main.py backtest data.csv --entry-tf 5min                    # default: 15min
py main.py backtest data.csv --min-score 50 --balance 50000
py main.py backtest data.csv --step 8 --save logs/results.json

# Check open positions for SL/TP fills
py main.py check-positions

# Show trading statistics / journal
py main.py stats
py main.py journal --limit 20

# Run tests
py -m pytest tests/ -v              # all 55 tests
py -m pytest tests/test_no_lookahead.py -v   # causality tests only
py -m pytest tests/test_trading.py -v        # trading module tests only
py -m pytest tests/ -k "test_fvg"            # run tests matching pattern

# Start real-time WebSocket position monitor (runs continuously)
py monitor.py

# Launch Streamlit dashboard
streamlit run ui/app.py
```

## Architecture

### Two Execution Paths

1. **Live Analysis** — `main.py analyze TICKER` fetches OHLC from Yahoo Finance, runs ICT detection, calls Claude CLI for trade decisions, opens paper positions. Scheduled via Windows Task Scheduler every 30 min.

2. **Backtesting** — `main.py backtest CSV` loads historical 1m data, resamples to all timeframes, walks forward through entry bars running the full ICT detection pipeline with point-in-time windowed data, uses deterministic rule-based decisions (no AI calls), simulates trades with position/risk management.

### Data Flow

```
Data Source (Yahoo Finance live OR historical CSV)
  -> ict/confluence.py (runs all ICT detectors across 4 timeframes)
  -> ai/analyst.py (live) OR backtest/rules.py (backtest)
  -> trading/risk.py validates -> positions.py opens trade
  -> SL/TP monitoring (monitor.py live, bar-by-bar in backtest)
  -> journal/logger.py logs everything
```

### Module Responsibilities

| Module | Key File | Does |
|--------|----------|------|
| `data/` | `yahoo.py`, `historical.py` | OHLC fetching (Yahoo REST) + historical CSV loader with contract stitching and resampling |
| `ict/` | `confluence.py`, `smc_patched.py`, `smc_adapter.py` | ICT detection engine — vendored SMC library (bias-free) + adapter + confluence scoring |
| `ai/` | `analyst.py` | Calls Claude Code CLI (`claude -p --model claude-sonnet-4-20250514`), parses JSON response |
| `trading/` | `risk.py`, `positions.py`, `account.py` | Paper trade lifecycle, risk validation, position sizing |
| `backtest/` | `engine.py`, `rules.py`, `report.py` | Walk-forward backtesting engine with rule-based decisions and analytics |
| `journal/` | `logger.py` | JSON trade log with ICT context snapshots |
| `tests/` | `test_no_lookahead.py`, `test_trading.py`, `test_data_historical.py` | 55 regression tests (causality, trading, data) |

### Vendored SMC Library (`ict/smc_patched.py`)

The `smartmoneyconcepts` package (v0.0.27) has critical look-ahead bias in its core functions. We vendor a patched copy at `ict/smc_patched.py` with these fixes:
- `swing_highs_lows()`: Replaced centered window with confirm-bars approach (no future data)
- `fvg()`: Output shifted forward by 1 bar (signal after 3rd candle closes)
- `bos_choch()`: Signals emitted at discovery time, not backdated to earlier swing
- No boundary swing injection at first/last bars

`ict/smc_adapter.py` wraps all calls to the patched library and supports runtime `swing_length` overrides for backtesting.

### ICT Detection Engine (`ict/`)

`confluence.py` orchestrates all detectors. The SMC library (via `smc_adapter.py`) handles: swings, BOS/CHoCH, FVGs, order blocks, liquidity, retracements, previous high/low. Custom detectors handle: displacement (`displacement.py`), kill zones (`killzones.py`), Fibonacci/OTE (`fib.py`), ATR (`candles.py`).

The SMC adapter is lazy-imported — setting `USE_SMC_LIBRARY=False` in config falls back to hand-rolled detectors without requiring the `smartmoneyconcepts` package.

## Multi-Timeframe Analysis

| Label | Timeframe | Purpose |
|-------|-----------|---------|
| `bias` | Daily | HTF market structure bias |
| `swing` | 4H | Intermediate structure (bias fallback when daily is neutral) |
| `setup` | 1H | Setup identification (FVGs, OBs) |
| `entry` | Configurable (1m/5m/15m) | Entry signals and trade execution |

For backtesting, all timeframes are resampled from 1m data. Bar timestamps use **bar-close labeling** (a 1H bar covering 10:00-10:59 is stamped 11:00) to prevent look-ahead bias in windowed analysis.

## Confluence Scoring (0-100)

| Factor | Weight |
|--------|--------|
| HTF bias aligned | 15 |
| FVG+OB overlap | 12 |
| FVG present | 10 |
| OB present | 10 |
| Liquidity sweep | 10 |
| OTE zone (61.8-79% Fib) | 10 |
| PDH/PDL target | 8 |
| Displacement (body > 2x ATR) | 8 |
| MSS (CHoCH + displacement) | 7 |
| Kill zone | 5 |
| Silver Bullet window | 5 |
| Premium/Discount aligned | 5 |
| CE at OB midpoint | 5 |

Minimum score to trade: 60. Weights defined in `config.CONFLUENCE_WEIGHTS`.

## Backtesting Rules

The backtest engine uses deterministic rules (`backtest/rules.py`). The live path (`main.py analyze`) also uses these same rules when `USE_AI_ANALYSIS = False` (current default). Set `True` in `config.py` to re-enable Claude AI decisions.

1. **HTF bias required** — daily must be bullish or bearish (falls back to 4H swing bias if daily is neutral)
2. **Kill zone gate** (non-crypto only) — entries only during London (2-5 AM ET), NY (7-11 AM ET), or Asian (7-10 PM ET)
3. **Dead zone block** — no entries during NY lunch (11 AM - 1 PM ET)
4. **Confluence >= 60**
5. **Actionable ICT levels** — needs FVG+OB overlap, standalone OB, or standalone FVG aligned with bias
6. **Minimum 2:1 R:R**
7. **Session-end close** (non-crypto) — all positions force-closed at 4 PM ET (day trades only, no overnight holds). SL/TP fills are checked BEFORE session-end so real fills take priority over synthetic close.

Crypto tickers (detected by `is_crypto()` or `--ticker BTC-USD`) bypass kill zone/dead zone/session-end rules.

## Risk Management

Enforced in `trading/risk.py`:
- Max 1% account per trade, minimum 2:1 R:R
- Max 3 concurrent positions, SL must be 0.1-5% from entry
- 10% drawdown from peak = circuit breaker
- Position sizing: `risk_amount / sl_distance`

## Trading Rules

- **Stocks and futures (ES, AAPL, etc.):** Day trades only. All positions closed by 4 PM ET. Never hold overnight.
- **Crypto (BTC-USD, etc.):** Can hold swing trades. Positions stay open until SL/TP hit.

## Key Files

- `config.py` — All constants: risk %, ATR params, kill zone times, confluence weights, swing lengths
- `ict/smc_patched.py` — Vendored + patched SMC library (no look-ahead bias)
- `logs/trades.json` — Trade journal (append-only)
- `BACKTESTING-FINDINGS.md` — Documented backtest results and analysis across ES and BTC
- `ICT_Trading_Strategies_Combined_Research.md` — ICT methodology reference

## Data Sources

| Source | Used For | Auth |
|--------|----------|------|
| Yahoo Finance | Live multi-timeframe OHLC | None (urllib) |
| Databento CSV | Historical backtesting (1m OHLCV) | Downloaded files |
| Alpaca Markets | Real-time WebSocket for position monitoring | Free API key (`.env`) |

## Credentials (`.env`)

```
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...
```

## Ticker Format

Yahoo Finance uses `BTC-USD`, Alpaca uses `BTC/USD`. Conversion helpers in `config.py`: `ticker_to_alpaca()` and `alpaca_to_ticker()`. Crypto detection (`is_crypto()` in `killzones.py`) checks for `-USD`, `-USDT` suffixes.

## Historical Data Format (Databento)

CSV columns: `ts_event, rtype, publisher_id, instrument_id, open, high, low, close, volume, symbol`. The `data/historical.py` loader handles contract stitching (ES roll dates), spread symbol filtering, and resampling from 1m to all timeframes.
