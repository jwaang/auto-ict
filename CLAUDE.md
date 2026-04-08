# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

ICT Paper Trading Simulator — applies Inner Circle Trader (ICT) methodology to paper trade any ticker. Fetches OHLC data, algorithmically detects ICT concepts (FVGs, OBs, market structure, etc.), sends context to Claude for trade decisions, simulates positions with full P&L tracking, and logs everything for re-analysis.

**No real trades are executed. This is a strategy testing tool.**

## Commands

```bash
# Run ICT analysis on a ticker (fetches data → detects levels → AI decision → paper trade)
py main.py analyze BTC-USD
py main.py analyze AAPL --balance 50000

# Check open positions for SL/TP fills
py main.py check-positions

# Show trading statistics
py main.py stats

# Show recent journal entries
py main.py journal --limit 20

# Backtest on historical 1-minute OHLCV data
py main.py backtest path/to/ohlcv-1m.csv
py main.py backtest data.csv --start 2025-04-07 --end 2025-07-01
py main.py backtest data.csv --min-score 50 --balance 50000
py main.py backtest data.csv --step 8 --save logs/my_backtest.json

# Start real-time WebSocket position monitor (runs continuously)
py monitor.py

# Launch Streamlit dashboard
streamlit run ui/app.py

# Automated run (called by Task Scheduler every 30 min)
py run.py
```

## Architecture

### Two-Layer Execution Model

1. **Scheduled Analysis (every 30 min)** — `run.py` via Windows Task Scheduler. Fetches multi-timeframe OHLC from Yahoo Finance, runs ICT detection, calls Claude Code CLI for trade decisions, opens paper positions.

2. **Continuous Monitor** — `monitor.py` runs as a persistent background process. Connects to Alpaca WebSocket, streams real-time minute bars for all open positions, closes positions instantly when SL/TP is hit.

### Data Flow

```
Yahoo Finance (daily/4h/1h/15m OHLC)
  → ict/confluence.py (runs all 8 ICT detectors across 4 timeframes)
  → ai/prompt.py (builds Claude prompt with all ICT levels)
  → ai/analyst.py (calls Claude Code CLI via subprocess)
  → Claude returns: LONG/SHORT, CONDITIONAL_LONG/SHORT, or NO_TRADE
  → If immediate: trading/risk.py validates → positions.py opens trade
  → If conditional: journal logs entry zones → monitor.py watches for price to enter zones
  → monitor.py: Alpaca WebSocket streams minute bars → checks SL/TP + conditional zone entry
  → On zone entry: ict/confirmation.py checks LTF confirmation (CHoCH, displacement, etc.)
  → If confirmed: auto-opens paper trade with risk validation
```

### Module Responsibilities

| Module | Key File | Does |
|--------|----------|------|
| `data/` | `yahoo.py`, `alpaca.py`, `historical.py` | OHLC fetching (Yahoo REST + Alpaca REST/WebSocket) + historical CSV loader |
| `ict/` | `confluence.py` | Orchestrates all 8 ICT detectors, scores setups 0-100 |
| `ai/` | `analyst.py` | Calls Claude Code CLI (`claude -p`), parses JSON response |
| `trading/` | `risk.py`, `positions.py`, `account.py` | Paper trade lifecycle, risk validation, position sizing |
| `journal/` | `logger.py` | JSON trade log with ICT context snapshots for re-analysis |
| `backtest/` | `engine.py`, `rules.py`, `report.py` | Walk-forward backtesting engine with rule-based decisions |
| `ui/` | `app.py` | Streamlit dashboard (4 tabs: dashboard, analysis, history, stats) |

### ICT Detection Engine (`ict/`)

Each detector is a separate module returning dicts. `confluence.py` orchestrates them all:

- `structure.py` — Swing highs/lows, BOS/CHoCH, market bias determination
- `fvg.py` — Fair Value Gap detection (3-candle imbalance pattern)
- `order_blocks.py` — Last opposing candle before displacement
- `displacement.py` — Impulsive candles (body > 2x ATR)
- `liquidity.py` — Swing clustering + sweep detection
- `killzones.py` — London/NY/Asian session time checks
- `fib.py` — Premium/Discount zones + OTE (61.8-79% Fibonacci)
- `candles.py` — ATR, body size, range helpers
- `confirmation.py` — Multi-TF entry confirmation (CHoCH, displacement, rejection wicks, FVG formation)

### Conditional Entry System

AI can output `CONDITIONAL_LONG`/`CONDITIONAL_SHORT` with prioritized entry zones instead of immediate trades. Each zone specifies price range, zone type (OB/FVG/OTE), stop loss, take profit, R:R, and what LTF confirmation is needed. The monitor watches for price to enter these zones, then runs `ict/confirmation.py` to check for entry signals on the appropriate confirmation timeframe.

Confirmation timeframe scales with zone origin:
- 4H zone → requires 1H confirmation (CHoCH or displacement, score >= 3)
- 1H zone → requires 15M confirmation (score >= 2)
- 15M zone → requires 15M confirmation (score >= 2)

### Confluence Scoring

Setups are scored 0-100. Below `MIN_CONFLUENCE_SCORE` (60), Claude is not consulted:
- HTF bias alignment: +20, FVG: +15, OB: +15, FVG+OB overlap: +15
- OTE zone: +10, Displacement: +10, Liquidity sweep: +10
- Kill zone: +5, Premium/Discount alignment: +5

### AI Integration

Uses Claude Code CLI (`claude -p`), NOT the Anthropic SDK directly. This runs on the user's Claude Pro/Max subscription with no API credits needed. The system prompt contains 10 ICT rules the AI must follow. Response is parsed as JSON.

## Data Sources

| Source | Used For | Auth |
|--------|----------|------|
| Yahoo Finance | Multi-timeframe OHLC (daily, 1h→4h aggregated, 1h, 15m) | None (urllib, unauthenticated) |
| Alpaca Markets | Real-time WebSocket minute bars for position monitoring | Free API key (`.env`) |

## Credentials (`.env`)

```
ALPACA_API_KEY=...        # Free from app.alpaca.markets
ALPACA_SECRET_KEY=...     # Free from app.alpaca.markets
```

Claude Code CLI authentication is handled by the user's existing login.

## Key Files

- `config.py` — All constants: risk %, ATR params, kill zone times, confluence weights, API keys
- `logs/trades.json` — Trade journal (append-only, includes AI reasoning + ICT context snapshots)
- `ICT-STRATEGY-GUIDE.md` — Comprehensive ICT methodology reference (21 sections)

## Ticker Format

Yahoo Finance uses `BTC-USD`, Alpaca uses `BTC/USD`. Conversion helpers in `config.py`: `ticker_to_alpaca()` and `alpaca_to_ticker()`.

## Multi-Timeframe Analysis

| Timeframe | Label | Source | Purpose |
|-----------|-------|--------|---------|
| Daily | `bias` | Yahoo `1d/6mo` | HTF market structure bias |
| 4H | `swing` | Yahoo `1h/1mo` aggregated to 4H | Swing structure, OBs, displacement legs |
| 1H | `setup` | Yahoo `1h/1mo` | Setup identification (FVGs, OBs) |
| 15M | `entry` | Yahoo `15m/5d` | Entry timing, OTE, kill zones |

4H candles are synthesized by aggregating 1H bars (Yahoo has no native 4H interval). The `aggregate_to` key in `config.TIMEFRAMES` controls this.

## Risk Management Rules

Enforced in `trading/risk.py`:
- Max 1% account per trade, minimum 2:1 R:R
- Max 3 concurrent positions, SL must be 0.1-5% from entry
- 10% drawdown from peak = circuit breaker (trading paused)
- If Claude says NO_TRADE, it's respected unconditionally
- Open position count is loaded from `journal/logger.py` (not in-memory) to survive process restarts
- Balance is derived from the most recently *closed* trade (sorted by `timestamp_closed`)

## Background Processes

- **Windows Task Scheduler** "ICT Paper Trader": runs `schedule.bat` every 30 minutes
- **Windows Startup Folder** `ICT-Price-Monitor.vbs`: launches `monitor.py` at login (persistent WebSocket monitor)
