"""Run a matrix of backtest configurations and record every result.

The point is accumulation: each cell appends one line to `logs/experiments.jsonl`
so results build up across sessions and the ranking is generated rather than
typed. Failures and zero-trade cells are recorded too, because the count of
configurations tried is what tells you how much of a good result is luck.

Workers receive the data file *path*, not the DataFrame. A 5-year 1-minute frame
is ~1.8M rows, and pickling that per cell would cost more than the backtest;
each worker process loads it once and caches it instead.
"""

from __future__ import annotations

import json
import math
import os
import time
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

STORE = Path("logs/experiments.jsonl")

_data_cache: dict[str, pd.DataFrame] = {}


def _load(path: str) -> pd.DataFrame:
    """Load and cache the 1m frame inside this worker process."""
    if path not in _data_cache:
        from data.historical import load_continuous_contract
        _data_cache[path] = load_continuous_contract(path)
    return _data_cache[path]


def _finite(value):
    """JSON has no infinity. calc_stats yields inf profit factor on zero losses."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _run_cell(data_path: str, cell: dict, ticker: str, starting_balance: float) -> dict:
    """Run one configuration. Never raises — a failed cell is a recorded row."""
    from backtest import params
    from backtest.engine import run_backtest
    from backtest.report import calc_stats

    started = time.time()
    row = {"label": cell.get("label", "unnamed"), "cell": cell, "error": None}
    try:
        df = _load(data_path)
        with params.overrides(cell.get("overrides")):
            result = run_backtest(
                df_1m=df,
                starting_balance=starting_balance,
                min_score=cell.get("min_score", 60),
                ticker=ticker,
                entry_tf=cell.get("entry_tf", "15min"),
                step_bars=cell.get("step_bars"),
                strategy=cell.get("strategy", "default"),
                trade_start=pd.Timestamp(cell["trade_start"], tz="UTC") if cell.get("trade_start") else None,
                trade_end=pd.Timestamp(cell["trade_end"], tz="UTC") if cell.get("trade_end") else None,
                progress_every=10**9,  # quiet inside a pool
            )
        stats = {k: _finite(v) for k, v in calc_stats(result).items()}
        row["stats"] = stats
        row["rejections"] = result.rejections
        row["parameters"] = result.parameters
        row["geometry"] = _geometry(result.trades)
        row["score_buckets"] = _score_buckets(result.trades)
        row["direction_split"] = _direction_split(result.trades)
    except Exception as exc:  # noqa: BLE001 - a broken cell must not kill the sweep
        row["error"] = f"{type(exc).__name__}: {exc}"
    row["seconds"] = round(time.time() - started, 1)
    return row


def _geometry(trades: list[dict]) -> dict:
    """Stop and target distances, plus the random-walk win rate they imply.

    Under a random walk with two absorbing barriers the chance of reaching the
    target first is stop/(stop+target). A strategy must beat its own benchmark,
    not 50%, so record it with every cell.
    """
    closed = [t for t in trades if t.get("status") == "CLOSED"]
    risks, rewards, null = [], [], []
    for t in closed:
        risk = abs(t["entry_price"] - t["stop_loss"])
        reward = abs(t["take_profit"] - t["entry_price"])
        if risk > 0:
            risks.append(risk)
            rewards.append(reward)
            null.append(risk / (risk + reward))
    if not risks:
        return {}
    return {
        "median_stop_pts": round(pd.Series(risks).median(), 2),
        "median_target_pts": round(pd.Series(rewards).median(), 2),
        "coinflip_win_rate": round(pd.Series(null).mean() * 100, 1),
    }


def _score_buckets(trades: list[dict]) -> dict:
    """Win rate per confluence score bucket.

    If this is flat or inverted, the confluence score is measuring lateness
    rather than edge — by the time N conditions confirm, the move is spent — and
    the fix is fewer, earlier conditions rather than a higher threshold.
    """
    closed = [t for t in trades if t.get("status") == "CLOSED"]
    if not closed:
        return {}
    df = pd.DataFrame([{
        "score": t.get("confluence_score") or 0,
        "win": 1 if (t.get("pnl_dollars") or 0) > 0 else 0,
    } for t in closed])
    df["bucket"] = pd.cut(df["score"], [0, 60, 65, 70, 75, 80, 101], right=False)
    grouped = df.groupby("bucket", observed=True).agg(n=("win", "size"), wins=("win", "sum"))
    grouped["win_rate"] = (grouped["wins"] / grouped["n"] * 100).round(1)
    return {str(k): v for k, v in grouped.to_dict("index").items()}


def _direction_split(trades: list[dict]) -> dict:
    """Long/short counts and win rates.

    A strategy that only ever goes one way is usually a broken bias rather than
    a view: the old bias function produced zero long signals across a rising year.
    """
    closed = [t for t in trades if t.get("status") == "CLOSED"]
    if not closed:
        return {}
    out = {}
    for side in ("LONG", "SHORT"):
        subset = [t for t in closed if t.get("direction") == side]
        if subset:
            wins = sum(1 for t in subset if (t.get("pnl_dollars") or 0) > 0)
            out[side] = {"n": len(subset), "win_rate": round(wins / len(subset) * 100, 1)}
        else:
            out[side] = {"n": 0, "win_rate": None}
    return out


def run_matrix(
    data_path: str,
    cells: list[dict],
    ticker: str = "ES",
    starting_balance: float = 100_000.0,
    max_workers: int | None = None,
    store: Path | str = STORE,
) -> list[dict]:
    """Run every cell in parallel and append each result to the store.

    Args:
        data_path: Path to the 1m data file, passed to workers rather than the frame
        cells: Config dicts. Recognised keys: label, entry_tf, strategy, min_score,
            step_bars, trade_start, trade_end, overrides
        max_workers: Defaults to cpu_count - 2, leaving headroom. The old
            optimize.py forked one process per config with no bound at all.

    Returns:
        The result rows, in completion order.
    """
    workers = max_workers or max(1, (os.cpu_count() or 4) - 2)
    run_id = uuid.uuid4().hex[:8]
    stamp = pd.Timestamp.now(tz="UTC").isoformat()
    store = Path(store)
    store.parent.mkdir(parents=True, exist_ok=True)

    print(f"  Running {len(cells)} cells on {workers} workers (run {run_id})")
    rows: list[dict] = []

    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_run_cell, data_path, cell, ticker, starting_balance): cell
            for cell in cells
        }
        for done, future in enumerate(as_completed(futures), start=1):
            cell = futures[future]
            try:
                row = future.result()
            except Exception as exc:  # worker died outright
                row = {"label": cell.get("label", "unnamed"), "cell": cell,
                       "error": f"worker died: {type(exc).__name__}: {exc}"}
            row["run_id"] = run_id
            row["recorded_at"] = stamp
            row["data"] = data_path
            rows.append(row)
            with store.open("a") as fh:
                fh.write(json.dumps(row, default=str) + "\n")

            stats = row.get("stats") or {}
            note = row["error"] or (
                f"{stats.get('total_trades', 0)} trades, "
                f"WR {stats.get('win_rate')}%, PF {stats.get('profit_factor')}, "
                f"{stats.get('return_pct')}%"
            )
            print(f"  [{done}/{len(cells)}] {row['label']}: {note}", flush=True)

    return rows


MIN_TRADES_TO_TRUST = 200   # below this a win rate is not a decision input
MIN_TRADES_TO_RANK = 30     # below this, do not even rank


def report(store: Path | str = STORE, top: int = 15) -> pd.DataFrame:
    """Print a ranked summary of everything recorded so far."""
    df = load_store(store)
    if df.empty:
        print("  No experiments recorded yet.")
        return df

    failed = df[df["error"].notna()]
    ok = df[df["error"].isna()].copy()
    print(f"\n  {len(df)} cells recorded across {df['run_id'].nunique()} runs "
          f"({len(failed)} failed, {len(ok)} usable)")

    if not ok.empty and "total_trades" in ok:
        thin = ok[ok["total_trades"] < MIN_TRADES_TO_RANK]
        rankable = ok[ok["total_trades"] >= MIN_TRADES_TO_RANK].copy()
        print(f"  {len(thin)} cells had under {MIN_TRADES_TO_RANK} trades and are unrankable")

        if not rankable.empty:
            # Edge over the random-walk benchmark implied by each cell's own
            # geometry, which is the only fair comparison across geometries.
            rankable["edge_vs_coinflip"] = (
                rankable["win_rate"] - rankable.get("coinflip_win_rate")
            ).round(1)
            cols = ["label", "trade_start", "trade_end", "entry_tf", "strategy",
                    "total_trades", "longs", "shorts", "win_rate",
                    "coinflip_win_rate", "edge_vs_coinflip", "avg_rr",
                    "profit_factor", "gross_pnl", "total_costs", "return_pct",
                    "max_drawdown_pct", "median_stop_pts", "median_target_pts",
                    "seconds", "top_rejection"]
            cols = [c for c in cols if c in rankable.columns]
            ranked = rankable.sort_values("edge_vs_coinflip", ascending=False)
            print("\n  Ranked by edge over each cell's own coin-flip benchmark:\n")
            print(ranked[cols].head(top).to_string(index=False))

            if "hypothesis" in ranked.columns:
                print("\n  Hypotheses, best first:\n")
                for _, row in ranked.head(top).iterrows():
                    if row.get("hypothesis"):
                        print(f"     {row['label']}  ({row.get('seconds', 0):.0f}s)")
                        print(f"        {row['hypothesis']}")

            trusted = ranked[ranked["total_trades"] >= MIN_TRADES_TO_TRUST]
            print(f"\n  {len(trusted)} of {len(ranked)} ranked cells reached "
                  f"{MIN_TRADES_TO_TRUST}+ trades. Treat the rest as suggestive only.")
            print(f"  Configurations tried so far: {len(df)}. With that many, "
                  f"require t > 3 before believing a winner.")

    if not failed.empty:
        print("\n  Failures:")
        for _, row in failed.head(10).iterrows():
            print(f"     {row['label']}: {row['error']}")
    return df


def load_store(store: Path | str = STORE) -> pd.DataFrame:
    """Read the whole experiment store into a flat frame for ranking."""
    store = Path(store)
    if not store.exists():
        return pd.DataFrame()
    records = []
    with store.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            flat = {
                "run_id": row.get("run_id"),
                "recorded_at": row.get("recorded_at"),
                "label": row.get("label"),
                "error": row.get("error"),
                "seconds": row.get("seconds"),
            }
            # Prefer the parameters the engine actually recorded — a cell may
            # omit a key and take the engine default, and the store must show
            # what ran, not what was requested.
            cell = row.get("cell") or {}
            recorded = row.get("parameters") or {}
            for key in ("entry_tf", "strategy", "min_score", "trade_start", "trade_end"):
                flat[key] = recorded.get(key, cell.get(key))
            flat["hypothesis"] = cell.get("hypothesis", "")
            for key in ("trade_start", "trade_end"):
                if flat[key]:
                    flat[key] = str(flat[key])[:10]
            flat["overrides"] = json.dumps((row.get("cell") or {}).get("overrides") or {}, sort_keys=True)
            for key, value in (row.get("stats") or {}).items():
                if not isinstance(value, (dict, list)):
                    flat[key] = value
            flat.update(row.get("geometry") or {})
            split = row.get("direction_split") or {}
            flat["longs"] = (split.get("LONG") or {}).get("n")
            flat["shorts"] = (split.get("SHORT") or {}).get("n")
            buckets = row.get("score_buckets") or {}
            if buckets:
                rates = [(k, v["win_rate"]) for k, v in buckets.items() if v.get("n", 0) >= 10]
                if len(rates) >= 2:
                    # Positive means higher scores won more often, which is what
                    # a confluence score is supposed to do.
                    flat["score_slope"] = round(rates[-1][1] - rates[0][1], 1)
            rej = row.get("rejections") or {}
            if rej:
                top = max(rej.items(), key=lambda kv: kv[1])
                flat["top_rejection"] = top[0]
                flat["top_rejection_n"] = top[1]
            records.append(flat)
    return pd.DataFrame(records)
