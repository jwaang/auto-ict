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
        row["excursion"] = _excursion_summary(result.trades)
        # Diagnostics come last and cannot take the run down with them. A
        # multi-hour backtest is too expensive to lose to an optional
        # measurement, and one of these did exactly that.
        for key, fn in (("null", _null_benchmark), ("setup_split", _setup_split)):
            try:
                row[key] = fn(df, result, cell)
            except Exception as exc:  # noqa: BLE001
                row[key] = {"error": f"{type(exc).__name__}: {exc}"}
    except Exception as exc:  # noqa: BLE001 - a broken cell must not kill the sweep
        row["error"] = f"{type(exc).__name__}: {exc}"
    row["seconds"] = round(time.time() - started, 1)
    return row


BARRIER_EXITS = ("SL_HIT", "TP_HIT")


def _geometry(trades: list[dict]) -> dict:
    """Stop and target distances, and the edge over the random-walk benchmark.

    Under a random walk with two absorbing barriers the chance of reaching the
    target first is stop/(stop+target). A strategy must beat its own benchmark,
    not 50%, so record it with every cell.

    The benchmark only describes trades that actually resolved at a barrier.
    Session-end and circuit-breaker closes touch neither — they exit at whatever
    price is there — so scoring them against a two-barrier null mixes
    populations. They tend to be small positive scratches, which inflates a
    headline win rate without carrying P&L, so the edge is computed over barrier
    exits alone and the rest is reported separately.
    """
    closed = [t for t in trades if t.get("status") == "CLOSED"]
    risks, rewards, null, wins = [], [], [], 0
    nonbarrier_n, nonbarrier_pnl = 0, 0.0
    for t in closed:
        pnl = t.get("pnl_dollars") or 0
        if t.get("exit_reason") not in BARRIER_EXITS:
            nonbarrier_n += 1
            nonbarrier_pnl += pnl
            continue
        risk = abs(t["entry_price"] - t["stop_loss"])
        reward = abs(t["take_profit"] - t["entry_price"])
        if risk > 0:
            risks.append(risk)
            rewards.append(reward)
            null.append(risk / (risk + reward))
            wins += 1 if pnl > 0 else 0
    out = {
        "barrier_n": len(risks),
        "nonbarrier_n": nonbarrier_n,
        "nonbarrier_pnl": round(nonbarrier_pnl, 2),
    }
    if not risks:
        return out
    coinflip = float(pd.Series(null).mean())
    out.update({
        "median_stop_pts": round(pd.Series(risks).median(), 2),
        "median_target_pts": round(pd.Series(rewards).median(), 2),
        "coinflip_win_rate": round(coinflip * 100, 1),
        "barrier_win_rate": round(wins / len(risks) * 100, 1),
    })
    out.update(_edge(wins, len(risks), coinflip))
    return out


def _edge(wins: int, n: int, coinflip: float) -> dict:
    """Edge in win-rate points over the benchmark, with its z score.

    z is the one-sample binomial test of the observed win count against the
    benchmark rate. It is the number to look at, not the edge: a large edge on
    twenty trades says nothing. With this many configurations tried, require
    z > 3 before believing a winner (Harvey, Liu and Zhu 2016).
    """
    if n <= 0:
        return {}
    observed = wins / n
    se = math.sqrt(coinflip * (1 - coinflip) / n)
    return {
        "barrier_edge": round((observed - coinflip) * 100, 1),
        "barrier_z": round((observed - coinflip) / se, 2) if se > 0 else None,
    }


def barrier_from_exit_reasons(exit_reasons: dict, coinflip: float | None) -> dict:
    """Recover barrier-only figures for a row recorded before the fix.

    Every run stores per-exit-reason counts, so the corrected metric is
    derivable from history rather than requiring a re-run. Recomputing a
    published number from data already on disk is a correction; editing the
    stored numbers would not be, so this derives and never mutates.
    """
    if not exit_reasons:
        return {}
    n = sum(d["n"] for r, d in exit_reasons.items() if r in BARRIER_EXITS)
    wins = sum(d["wins"] for r, d in exit_reasons.items() if r in BARRIER_EXITS)
    other = [(r, d) for r, d in exit_reasons.items() if r not in BARRIER_EXITS]
    out = {
        "barrier_n": n,
        "nonbarrier_n": sum(d["n"] for _, d in other),
        "nonbarrier_pnl": round(sum(d["net_pnl"] for _, d in other), 2),
    }
    if n > 0:
        out["barrier_win_rate"] = round(wins / n * 100, 1)
        if coinflip is not None:
            out.update(_edge(wins, n, coinflip / 100))
    return out


def _null_benchmark(df_1m, result, cell: dict, draws: int = 6000) -> dict:
    """Score the cell against random entries at its own geometry.

    `stop / (stop + target)` assumes unlimited time to resolve, but positions are
    force-closed at 16:00 ET. The target is farther away than the stop, so it
    needs more time, and the cutoff removes target-hits more often than
    stop-hits — which makes the formula too generous a benchmark. Measured on ES,
    the overstatement runs about 0.1 points at a 1.7x target and 2 to 3.4 points
    at 2.5x, so it matters exactly where the targets are widest.

    Random entries on the same bars, at the same geometry, under the same cutoff,
    remove the assumption entirely. Six thousand draws take about a tenth of a
    second, so there is no reason to keep guessing.
    """
    from data.historical import resample_ohlcv
    from backtest.nullmodel import (
        geometry_from_trades,
        paired_geometry_from_trades,
        run_null_model,
    )

    stops, mults = geometry_from_trades(result.trades)
    if len(stops) == 0:
        return {}
    lo = pd.Timestamp(cell["trade_start"], tz="UTC") if cell.get("trade_start") else df_1m["timestamp"].iloc[0]
    hi = pd.Timestamp(cell["trade_end"], tz="UTC") + pd.Timedelta(days=1) if cell.get("trade_end") else df_1m["timestamp"].iloc[-1]
    span = df_1m[(df_1m["timestamp"] >= lo) & (df_1m["timestamp"] < hi)].reset_index(drop=True)
    if span.empty:
        return {}
    bars = resample_ohlcv(span, cell.get("entry_tf", "15min"), session_aligned=True)
    from backtest.intrabar import Intrabar
    view, closes = Intrabar(span), span.set_index("timestamp")["close"]
    # Seeded on the label so a cell's null is fixed and cannot be re-rolled.
    out = run_null_model(span, pd.DatetimeIndex(bars["timestamp"]), stops, mults,
                         n=draws, seed=abs(hash(cell.get("label", ""))) % 2**31,
                         intrabar=view, closes=closes)
    null_rate = out.get("null_win_rate")
    barrier = _geometry(result.trades)
    wins = None
    if barrier.get("barrier_n"):
        wins = int(round(barrier["barrier_win_rate"] / 100 * barrier["barrier_n"]))
    if null_rate is not None and wins is not None:
        edge = _edge(wins, barrier["barrier_n"], null_rate / 100)
        out["edge_vs_null"] = edge.get("barrier_edge")
        out["z_vs_null"] = edge.get("barrier_z")

    # The paired null reuses each trade's own bar and geometry and randomises
    # only direction, so censoring is matched exactly. Comparing the two splits
    # the result into timing skill and direction skill.
    times, pstops, pmults = paired_geometry_from_trades(result.trades)
    if len(times):
        pair = run_null_model(span, times, pstops, pmults, n=draws,
                              seed=abs(hash(cell.get("label", "") + "paired")) % 2**31,
                              paired=True, intrabar=view, closes=closes)
        out["paired_null_win_rate"] = pair.get("null_win_rate")
        out["paired_null_censored_pct"] = pair.get("null_censored_pct")
        if pair.get("null_win_rate") is not None and wins is not None:
            edge = _edge(wins, barrier["barrier_n"], pair["null_win_rate"] / 100)
            out["edge_vs_paired_null"] = edge.get("barrier_edge")
            out["z_vs_paired_null"] = edge.get("barrier_z")
    return out


def _setup_split(df_1m, result, cell: dict) -> dict:
    """Barrier win rate and matched null per setup type.

    A total edge of zero can mean every concept is noise, or that some carry
    positive edge and others negative and they cancel. The confluence score adds
    them up without distinguishing, and it has no predictive slope, which fits
    the cancellation story. Each setup type has its own stop and target
    distribution, so each needs its own null rather than a shared one.

    One run answers this, so it costs a per-type null — a tenth of a second each
    — rather than a sweep.
    """
    from data.historical import resample_ohlcv
    from backtest.intrabar import Intrabar
    from backtest.nullmodel import geometry_from_trades, run_null_model

    closed = [t for t in result.trades if t.get("status") == "CLOSED"]
    by_type: dict[str, list] = {}
    for t in closed:
        by_type.setdefault(t.get("setup_type") or "UNKNOWN", []).append(t)
    if len(by_type) < 2:
        return {}

    lo = pd.Timestamp(cell["trade_start"], tz="UTC") if cell.get("trade_start") else df_1m["timestamp"].iloc[0]
    hi = pd.Timestamp(cell["trade_end"], tz="UTC") + pd.Timedelta(days=1) if cell.get("trade_end") else df_1m["timestamp"].iloc[-1]
    span = df_1m[(df_1m["timestamp"] >= lo) & (df_1m["timestamp"] < hi)].reset_index(drop=True)
    if span.empty:
        return {}
    bars = resample_ohlcv(span, cell.get("entry_tf", "15min"), session_aligned=True)
    entry_times = pd.DatetimeIndex(bars["timestamp"])
    # One view for every type, not one per type.
    view, closes = Intrabar(span), span.set_index("timestamp")["close"]

    out = {}
    for name, trades in sorted(by_type.items()):
        geom = _geometry(trades)
        entry = {
            "n": len(trades),
            "barrier_n": geom.get("barrier_n", 0),
            "barrier_win_rate": geom.get("barrier_win_rate"),
            "net_pnl": round(sum(t.get("pnl_dollars") or 0 for t in trades), 2),
        }
        stops, mults = geometry_from_trades(trades)
        if len(stops) and entry["barrier_n"]:
            null = run_null_model(span, entry_times, stops, mults, n=4000,
                                  seed=abs(hash(name)) % 2**31,
                                  intrabar=view, closes=closes)
            rate = null.get("null_win_rate")
            if rate is not None:
                wins = round(entry["barrier_win_rate"] / 100 * entry["barrier_n"])
                edge = _edge(int(wins), entry["barrier_n"], rate / 100)
                entry["null_win_rate"] = rate
                entry["edge_vs_null"] = edge.get("barrier_edge")
                entry["z_vs_null"] = edge.get("barrier_z")
        out[name] = entry
    return out


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


def _excursion_summary(trades: list[dict]) -> dict:
    """Whether the target was ever reachable, measured on 1-minute bars.

    `target_r` is what the strategy asked for. If `mfe_r` on winners barely
    clears it and on losers sits far below, the target is unreachable by
    construction and entry tuning cannot help. `mae_r` on winners says how close
    the stop came to being grazed — high values mean a slightly wider stop would
    convert losses into wins.
    """
    closed = [t for t in trades if t.get("status") == "CLOSED" and t.get("mfe_r") is not None]
    if not closed:
        return {}
    frame = pd.DataFrame([{
        "mfe_r": t["mfe_r"],
        "mae_r": t["mae_r"],
        "target_r": (abs(t["take_profit"] - t["entry_price"])
                     / abs(t["entry_price"] - t["stop_loss"]))
        if abs(t["entry_price"] - t["stop_loss"]) else None,
        "win": (t.get("pnl_dollars") or 0) > 0,
    } for t in closed])

    out = {
        "n": len(frame),
        "median_target_r": round(frame["target_r"].median(), 2),
        "median_mfe_r": round(frame["mfe_r"].median(), 2),
        "median_mae_r": round(frame["mae_r"].median(), 2),
    }
    # The decisive number: how often price ever travelled as far as the target.
    reached = frame["mfe_r"] >= frame["target_r"]
    out["pct_reached_target_r"] = round(reached.mean() * 100, 1)
    for label, subset in (("winners", frame[frame["win"]]), ("losers", frame[~frame["win"]])):
        if not subset.empty:
            out[f"median_mfe_r_{label}"] = round(subset["mfe_r"].median(), 2)
            out[f"median_mae_r_{label}"] = round(subset["mae_r"].median(), 2)
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
            # geometry, measured over barrier exits only. Ranking on the overall
            # win rate instead flatters any config that force-closes a lot of
            # small winners at the session end, because those resolve at neither
            # barrier and so are not what the benchmark describes.
            cols = ["label", "trade_start", "trade_end", "entry_tf", "strategy",
                    "total_trades", "barrier_n", "longs", "shorts",
                    "barrier_win_rate", "null_win_rate", "edge_vs_null",
                    "z_vs_null", "coinflip_win_rate", "barrier_edge",
                    "barrier_z", "win_rate", "nonbarrier_n", "nonbarrier_pnl",
                    "avg_rr", "profit_factor", "gross_pnl", "total_costs",
                    "return_pct", "max_drawdown_pct", "median_stop_pts",
                    "median_target_pts", "seconds", "top_rejection"]
            cols = [c for c in cols if c in rankable.columns]
            # Prefer the measured null; fall back to the formula for old rows
            # that predate it.
            sort_key = ("edge_vs_null" if rankable.get("edge_vs_null") is not None
                        and rankable["edge_vs_null"].notna().any() else "barrier_edge")
            ranked = rankable.sort_values(sort_key, ascending=False)
            print(f"\n  Ranked by {sort_key} — edge over random entries at the same"
                  "\n  geometry, barrier exits only (z is the number to trust):\n")
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
            geom = row.get("geometry") or {}
            flat.update(geom)
            for key, value in (row.get("null") or {}).items():
                flat[key] = value
            if "barrier_win_rate" not in geom:
                # Recorded before the benchmark was restricted to barrier exits.
                # Derive it from the stored exit-reason counts so old rows stay
                # comparable instead of ranking on the inflated metric.
                flat.update(barrier_from_exit_reasons(
                    (row.get("stats") or {}).get("exit_reasons") or {},
                    geom.get("coinflip_win_rate"),
                ))
            for key, value in (row.get("excursion") or {}).items():
                flat[key if key.startswith("median") or key.startswith("pct") else f"exc_{key}"] = value
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
