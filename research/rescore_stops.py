"""Re-resolve experiment 26's trades at a range of stop widths.

The break-even bar falls as 1.02/stop, from about +3.5 win-rate points at the
observed ~9.2-point stop to about +1.2 at 30 points. The measured direction edge
is +1.2. So the whole question is the shape of edge against stop width, and one
offline pass over the stored trades answers it without changing the population.

Two counterfactuals, because they mean different things and the choice is not
obvious:

  fixed_target — widen the stop, leave the target at the price it was. The
    engine picks targets from liquidity levels, so that price is where the
    liquidity sits and it does not move because the stop moved. This is the
    primary reading of "does a wider stop pay".

  fixed_mult   — widen the stop and push the target out with it, keeping R:R.
    This asks whether the signal works at the same shape but a larger scale.
    It assumes liquidity targets scale with the stop, which nothing establishes.

Censoring is reported per row rather than assumed harmless. The paired null
shares the 16:00 cutoff, but if correctly-directed trades resolve at a different
rate from wrongly-directed ones then conditioning on resolution biases the
direction edge itself, not only its interval. Mean net R over *all* trades,
closing the unresolved ones at the cutoff, sidesteps that conditioning entirely.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest.experiments import _edge
from backtest.intrabar import Intrabar
from backtest.nullmodel import run_null_model, session_end
from data.historical import load_continuous_contract

TRADES = "logs/exp27/exp26_trades.json"
DATA = "historical/ES-5y/glbx-mdp3-20210724-20260723.ohlcv-1m.dbn.zst"
COST_POINTS = 1.02          # spread + slippage + commission, one round turn on ES
STOPS = [None, 15.0, 20.0, 30.0, 40.0, 60.0]   # None = each trade's own stop
NULL_DRAWS = 6000

blob = json.load(open(TRADES))
raw = blob["trades"]

trades = []
for t in raw:
    if t.get("status") != "CLOSED" or not t.get("entry_time"):
        continue
    entry = float(t["entry_price"])
    risk = abs(entry - float(t["stop_loss"]))
    reward = abs(float(t["take_profit"]) - entry)
    if risk <= 0 or reward <= 0:
        continue
    trades.append({
        "ts": pd.Timestamp(t["entry_time"]),
        "dir": t["direction"],
        "entry": entry,
        "risk": risk,
        "reward": reward,
    })
print(f"{len(trades)} usable trades of {len(raw)} recorded", flush=True)

df = load_continuous_contract(DATA)
intrabar = Intrabar(df)
closes = df.set_index("timestamp")["close"]

idx = pd.DatetimeIndex([t["ts"] for t in trades])
if idx.tz is None:
    idx = idx.tz_localize("UTC")


def close_at(ts):
    """Last traded price at or before the cutoff."""
    i = closes.index.searchsorted(ts, side="right") - 1
    return float(closes.iloc[i]) if i >= 0 else None


def resolve(stop_width, mode):
    """Outcome, R and geometry for every trade at one stop width."""
    stops, mults, outcomes, rs = [], [], [], []
    for t in trades:
        s = t["risk"] if stop_width is None else stop_width
        if mode == "fixed_target":
            reward = t["reward"]
        else:
            reward = s * (t["reward"] / t["risk"])
        m = reward / s
        sign = 1.0 if t["dir"] == "LONG" else -1.0
        stop = t["entry"] - sign * s
        target = t["entry"] + sign * reward

        end = session_end(t["ts"])
        out = intrabar.first_touch(t["ts"], end, t["dir"], stop, target)
        cost = COST_POINTS / s

        if out == "TP_HIT":
            r = m - cost
        elif out == "SL_HIT":
            r = -1.0 - cost
        else:
            px = close_at(end)
            r = None if px is None else (px - t["entry"]) * sign / s - cost

        stops.append(s)
        mults.append(m)
        outcomes.append(out)
        rs.append(r)
    return np.asarray(stops), np.asarray(mults), outcomes, rs


def row(stop_width, mode):
    stops, mults, outcomes, rs = resolve(stop_width, mode)
    tp = sum(1 for o in outcomes if o == "TP_HIT")
    sl = sum(1 for o in outcomes if o == "SL_HIT")
    n = tp + sl
    censored = len(outcomes) - n

    null = run_null_model(df, idx, stops, mults, n=NULL_DRAWS, seed=11,
                          paired=True, intrabar=intrabar, closes=closes)
    null_wr = null.get("null_win_rate")
    e = _edge(tp, n, null_wr / 100) if (n and null_wr is not None) else {}

    # Break-even needs WR = (1 + cost_share)/(1 + m); the benchmark is 1/(1 + m);
    # so the edge a config must clear is cost_share/(1 + m), averaged per trade.
    bar = float(np.mean((COST_POINTS / stops) / (1 + mults))) * 100
    live = [r for r in rs if r is not None]
    mean_r = float(np.mean(live)) if live else float("nan")
    t_stat = (mean_r / (float(np.std(live, ddof=1)) / np.sqrt(len(live)))
              if len(live) > 1 and np.std(live, ddof=1) > 0 else float("nan"))

    return {
        "stop": "actual" if stop_width is None else f"{stop_width:.0f}",
        "med_stop": round(float(np.median(stops)), 2),
        "med_mult": round(float(np.median(mults)), 2),
        "barrier_n": n,
        "cens_pct": round(censored / len(outcomes) * 100, 1),
        "null_cens_pct": null.get("null_censored_pct"),
        "wr": round(tp / n * 100, 2) if n else None,
        "null_wr": null_wr,
        "edge": e.get("barrier_edge"),
        "z": e.get("barrier_z"),
        "bar": round(bar, 2),
        "mean_r": round(mean_r, 4),
        "t_r": round(t_stat, 2),
    }


HEAD = ("stop  medstop medmult  barn  cens%  ncens%     wr  nullwr   edge      z"
        "    bar   meanR    t_R")
for mode in ("fixed_target", "fixed_mult"):
    print(f"\n=== {mode} ===", flush=True)
    print(HEAD, flush=True)
    results = []
    for s in STOPS:
        r = row(s, mode)
        results.append(r)
        print(f"{r['stop']:>5} {r['med_stop']:>7} {r['med_mult']:>7} "
              f"{r['barrier_n']:>5} {r['cens_pct']:>6} {r['null_cens_pct']:>7} "
              f"{r['wr']:>6} {r['null_wr']:>7} {r['edge']:>6} {r['z']:>6} "
              f"{r['bar']:>6} {r['mean_r']:>7} {r['t_r']:>6}", flush=True)
    json.dump(results, open(f"logs/exp27/rescore_{mode}.json", "w"),
              indent=2)
