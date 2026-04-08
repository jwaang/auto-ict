# Repository Guidelines

## Project Structure & Module Organization
`main.py` is the CLI entry point for analysis, stats, journaling, and position checks. Core logic is split by responsibility: `ict/` contains detection and confluence scoring, `trading/` manages risk and paper positions, `journal/` persists trade history, `data/` fetches market data, `ai/` builds prompts and calls the Claude CLI, and `ui/app.py` provides the Streamlit dashboard. Runtime artifacts live in `logs/`; sample market data lives in `datasets/`. Add new automated tests under `tests/`.

## Build, Test, and Development Commands
Create an environment and install dependencies with `py -m pip install -r requirements.txt`.

- `py main.py analyze BTC-USD` runs the full ICT analysis and paper-trade flow.
- `py main.py check-positions` evaluates open trades against the latest data.
- `py run.py` executes the scheduled analysis cycle used by Task Scheduler.
- `py monitor.py` starts the continuous Alpaca-based fill monitor.
- `streamlit run ui/app.py` launches the local dashboard.

## Coding Style & Naming Conventions
Target Python 3.12 style already used in the repo: 4-space indentation, type hints where practical, and small focused modules. Use `snake_case` for functions, variables, and modules; `PascalCase` for classes; and uppercase names for configuration constants in `config.py`. Prefer explicit imports from package modules, keep docstrings short, and avoid mixing business logic into UI or scheduler scripts.

## Testing Guidelines
There is no committed test suite yet, so new work should add focused `pytest` coverage in `tests/` using names like `test_risk_rejects_low_rr.py`. Prioritize deterministic tests around `ict/`, `trading/`, and `journal/` logic. Before opening a PR, run at minimum `py -m pytest` and a targeted smoke check such as `py main.py stats` or `py main.py analyze AAPL`.

## Commit & Pull Request Guidelines
This workspace snapshot does not include `.git` history, so use clear imperative commit messages such as `feat: add conditional entry validation` or `fix: handle empty Yahoo candles`. Keep each commit scoped to one change. PRs should include a short summary, test evidence, any config or scheduler impact, and screenshots when `ui/app.py` changes.

## Security & Configuration Tips
Keep secrets only in `.env`; never commit API keys or edited log snapshots. Treat `logs/trades.json` as runtime data, not source. If you change ticker formatting or external API behavior, preserve the Yahoo `BTC-USD` and Alpaca `BTC/USD` conversion helpers in `config.py`.
