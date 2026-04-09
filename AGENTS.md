# Repository Guidelines

## Project Structure & Module Organization
`main.py` is the CLI entry point for analysis, live trading, stats, journaling, and position checks. `live.py` is the continuous streaming daemon. Core logic is split by responsibility: `broker/` manages the IBKR connection and order execution, `ict/` contains detection and confluence scoring, `trading/` manages risk and position simulation (backtesting), `journal/` persists trade history, `data/` loads historical CSV data (backtesting), `ai/` builds prompts and calls the Claude CLI, and `ui/app.py` provides the Streamlit dashboard. Runtime artifacts live in `logs/`.

## Build, Test, and Development Commands
Create an environment and install dependencies with `py -m pip install -r requirements.txt`.

- `py main.py live` starts continuous live trading (streams bars, auto-analyzes, places orders).
- `py main.py analyze MES` runs a one-shot ICT analysis on MES via IBKR.
- `py main.py check-positions` shows open IBKR positions and orders.
- `py main.py backtest data.csv` runs walk-forward backtesting on historical data.
- `streamlit run ui/app.py` launches the local dashboard.

## Coding Style & Naming Conventions
Target Python 3.12 style already used in the repo: 4-space indentation, type hints where practical, and small focused modules. Use `snake_case` for functions, variables, and modules; `PascalCase` for classes; and uppercase names for configuration constants in `config.py`. Prefer explicit imports from package modules, keep docstrings short, and avoid mixing business logic into UI scripts.

## Testing Guidelines
Run `py -m pytest tests/ -v` for all 55 tests. New work should add focused `pytest` coverage in `tests/`. Prioritize deterministic tests around `ict/`, `trading/`, and `journal/` logic.

## Commit & Pull Request Guidelines
Use clear imperative commit messages such as `feat: add conditional entry validation` or `fix: handle empty candles`. Keep each commit scoped to one change.

## Security & Configuration Tips
Keep secrets only in `.env`; never commit API keys or edited log snapshots. Treat `logs/trades.json` as runtime data, not source. IBKR connects via local TCP socket (no API keys needed).
