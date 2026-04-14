# ICT Paper Trading Simulator

Algorithmic paper trading system that applies Inner Circle Trader (ICT) methodology to ES/MES futures via Interactive Brokers. Detects ICT concepts (FVGs, Order Blocks, market structure shifts, liquidity sweeps), scores setups through confluence analysis, and executes bracket orders on an IBKR paper account.

Includes a walk-forward backtesting engine with no look-ahead bias and a threshold optimizer with train/test validation.

**Paper trading only. No real money at risk.**

## Features

- **Live trading** via IBKR paper account (TWS/Gateway) with real-time bar streaming
- **Walk-forward backtesting** on 1-minute historical data resampled to any timeframe
- **Three strategy modes:** confluence scoring (default), ICT 2022 Model, Silver Bullet
- **ICT detection engine:** FVGs, Order Blocks, BOS/CHoCH, liquidity zones, Breaker Blocks, Inversion FVGs, Power of 3 / Judas Swing, OTE zones, displacement
- **4-factor daily bias:** structure direction + liquidity draw + premium/discount + raid status
- **Risk management:** 1% per trade, circuit breaker at 10% drawdown, per-asset SL sizing
- **Walk-forward optimizer** with parallel threshold search and train/test split
- **Historical data download** from IBKR with full 23-hour session coverage

## Quick Start

### Prerequisites

- Python 3.12+
- Interactive Brokers TWS or IB Gateway (paper trading mode)
- CME market data subscription (~$1-5/mo for non-professional)

### Setup

```bash
pip install -r requirements.txt
```

Start TWS or IB Gateway, log in with your paper trading account, and enable API connections (port 7497 for TWS paper, 4002 for Gateway paper).

### Download Historical Data

```bash
py main.py download-history --symbol ES --days 180
```

### Run a Backtest

```bash
# Default confluence strategy
py main.py backtest historical/ES-data.csv --ticker ES --entry-tf 15min

# ICT 2022 Model (sweep -> MSS -> FVG sequence)
py main.py backtest historical/ES-data.csv --ticker ES --entry-tf 5min --strategy ict_2022

# Silver Bullet (3 narrow time windows)
py main.py backtest historical/ES-data.csv --ticker ES --entry-tf 5min --strategy silver_bullet

# With date range
py main.py backtest historical/ES-data.csv --ticker ES --start 2026-01-01 --end 2026-04-01 --entry-tf 5min

# Quick regime test (4 representative weeks: uptrend, downtrend, choppy, low-vol)
py main.py backtest historical/ES-data.csv --regime-test --entry-tf 5min
```

### Optimize Threshold

```bash
py main.py optimize historical/ES-data.csv --ticker ES --entry-tf 15min --thresholds 30,40,50,60,70,80
```

### Live Trading

```bash
# Continuous streaming (connects to IBKR, streams bars, auto-trades)
py main.py live

# One-shot analysis
py main.py analyze MES
```

### Other Commands

```bash
py main.py check-positions          # Open IBKR positions and orders
py main.py stats                    # Trading statistics
py main.py journal --limit 20      # Recent journal entries
streamlit run ui/app.py             # Streamlit dashboard
```

## Architecture

```
Live:     IBKR bar stream -> ICT detection -> confluence scoring -> risk validation -> bracket order
Backtest: Historical CSV  -> ICT detection -> rule-based decision -> position simulation -> P&L report
```

### Multi-Timeframe Analysis

| Timeframe | Purpose |
|-----------|---------|
| Daily | HTF bias (4-factor: structure + liquidity + premium/discount + raids) |
| 4H | Intermediate structure, bias fallback |
| 1H | Setup identification |
| 1m/5m/15m | Entry signals and execution |

### Detection Pipeline

The vendored `smc_patched.py` (smartmoneyconcepts v0.0.27 with look-ahead bias fixes) provides core detections: swing highs/lows, BOS/CHoCH, FVGs, Order Blocks, liquidity zones, retracements, PDH/PDL.

Additional detectors: Breaker Blocks, Inversion FVGs, Power of 3 / Judas Swing, displacement, OTE/Fibonacci, kill zones.

### Confluence Scoring (0-100)

17 weighted factors including HTF bias alignment (15), FVG+OB overlap (12), liquidity sweep (10), PO3 Judas Swing (10), OTE zone (10), Breaker Block (8), and more. Minimum 60 to trade.

### Entry Priority (Futures)

1. **FVG+OB overlap** -- strongest confluence, always allowed
2. **FVG+OTE** -- standalone FVG only when in OTE zone (61.8-79% fib retracement)
3. Standalone OB and standalone FVG filtered out for futures (underperform)

## Backtest Results

Best configuration on 6-month IBKR ES data (5min entry, kill zones off):

| Metric | Value |
|--------|-------|
| Net P&L | +$72,943 (+72.9%) |
| Win Rate | 34.3% |
| Profit Factor | 1.71 |
| Total Trades | 242 |
| Max Drawdown | 10.9% |

See `docs/BACKTEST-RESULTS-LOG.md` for comprehensive results across all experiments.

Backtests auto-generate `logs/backtest_trades.csv` with per-trade details (entry/exit times, reasoning, ICT concepts, bias, confluence score, outcome) for manual review against charts.

## Project Structure

```
main.py                 CLI entry point
live.py                 Continuous live trading daemon
config.py               All configuration constants

ict/
  smc_patched.py        Vendored SMC library (no look-ahead bias) -- do not modify
  smc_adapter.py        Wrapper for smc_patched with caching
  confluence.py         Detection orchestrator + scoring + 4-factor bias
  breaker_blocks.py     Breaker Block detector
  ifvg.py               Inversion FVG detector
  po3.py                Power of 3 / Judas Swing detector
  killzones.py          Time-based session filters
  displacement.py       Displacement candle detection
  fib.py                Fibonacci / OTE calculations

backtest/
  engine.py             Walk-forward backtesting engine
  rules.py              Deterministic trade decision rules
  report.py             Performance analytics, reporting, trade log CSV export
  optimize.py           Walk-forward threshold optimizer (parallel)
  regimes.py            Regime-based test presets (4 weeks per asset)
  strategies/           ICT 2022 Model + Silver Bullet strategies

trading/
  positions.py          Position lifecycle + trade management
  risk.py               Risk validation (futures-aware)
  account.py            Account tracking + circuit breaker

broker/
  ibkr.py               IBKR connection, orders, historical download

data/
  historical.py         CSV loader (Databento + IBKR formats), resampling

docs/
  ICT_Trading_Strategies_Combined_Research.md    ICT methodology reference
  BACKTEST-RESULTS-LOG.md                        All backtest experiments and findings
```

## Testing

```bash
py -m pytest tests/ -v              # All tests
py -m pytest tests/test_no_lookahead.py -v   # Causality/look-ahead bias tests
py -m pytest tests/test_trading.py -v        # Trading module tests
```

## Configuration

Key settings in `config.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `ENFORCE_KILL_ZONES` | `False` | Kill zone / dead zone time filtering |
| `TRADE_MANAGEMENT_ENABLED` | `False` | Partial TP at 1R + trailing SL |
| `MIN_CONFLUENCE_SCORE` | `60` | Minimum score to enter a trade |
| `RISK_PER_TRADE_PCT` | `1.0` | Max account risk per trade (%) |
| `MAX_DRAWDOWN_PCT` | `10.0` | Circuit breaker threshold (%) |
| `SPREAD_POINTS` | `0.0` | Bid-ask spread modeling (points) |
| `SLIPPAGE_POINTS` | `0.0` | Per-fill slippage modeling (points) |

## Data Sources

| Source | Used For |
|--------|----------|
| Interactive Brokers | Live trading, historical download (`download-history`) |
| Databento CSV | Historical backtesting (pre-downloaded 1m OHLCV) |

## Disclaimer

This is a paper trading simulator for educational and research purposes. It trades exclusively on IBKR paper accounts. Past backtest performance does not guarantee future results. The ICT methodology described here is based on publicly available educational material.
