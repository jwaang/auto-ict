"""Score one entry-timeframe cell, and check it is measurable at all first.

Three things, in this order, because the later ones are meaningless without the
earlier ones:

1. Resolver agreement. The engine decides a fill from the entry candle's high
   and low, while every null is resolved on 1-minute data by
   `Intrabar.first_touch`. The coarser the entry bar, the more often both
   barriers sit inside one candle and the two can disagree. Experiment 27 was
   the case where they did, and it cost a published conclusion.
2. The edge over a matched paired null, across 30 seeds, because one seed
   carries about 0.7 win-rate points of noise.
3. The two hurdles. The economic bar is `cost_share / (1 + m)` and falls as
   stops widen. The statistical hurdle is 3 standard errors of the win rate and
   *rises* as the trade count falls. Coarsening the timeframe moves them in
   opposite directions, so both are printed and the binding one is named.
"""
import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest.experiments import _edge
from backtest.intrabar import Intrabar
from backtest.nullmodel import run_null_model, paired_geometry_from_trades, session_end
from data.historical import load_continuous_contract

import pandas as pd

DATA = "historical/ES-5y/glbx-mdp3-20210724-20260723.ohlcv-1m.dbn.zst"
COST_POINTS = 1.02
CELLS = json.loads(os.environ.get("EXP_CELLS", '{"15m":"logs/exp27/exp26_trades.json"}'))

df = load_continuous_contract(DATA)
ib = Intrabar(df)
closes = df.set_index("timestamp")["close"]

for tag, path in CELLS.items():
    if not Path(path).exists():
        print(f"{tag}: missing {path}")
        continue
    trades = json.load(open(path))["trades"]
    closed = [t for t in trades if t.get("status") == "CLOSED"]

    agree = disagree = 0
    for t in closed:
        if not t.get("entry_time"):
            continue
        ts = pd.Timestamp(t["entry_time"])
        mine = ib.first_touch(ts, session_end(ts), t["direction"],
                              float(t["stop_loss"]), float(t["take_profit"]))
        eng = t.get("exit_reason")
        same = (eng == mine) or (eng == "SESSION_END" and mine is None)
        agree += same
        disagree += not same

    tp = sum(1 for t in closed if t.get("exit_reason") == "TP_HIT")
    n = tp + sum(1 for t in closed if t.get("exit_reason") == "SL_HIT")
    times, stops, mults = paired_geometry_from_trades(trades)

    edges = [_edge(tp, n, run_null_model(df, times, stops, mults, n=6000, seed=k,
                                         paired=True, intrabar=ib, closes=closes)
                   ["null_win_rate"] / 100)["barrier_edge"] for k in range(30)]
    e = np.array(edges)

    wr = tp / n if n else float("nan")
    bar = float(np.mean((COST_POINTS / stops) / (1 + mults))) * 100
    se = float(np.sqrt(wr * (1 - wr) / n)) * 100 if n else float("nan")
    stat_hurdle = 3 * se

    print(f"\n=== {tag} ===  {path}")
    print(f"  resolver      {agree} agree / {disagree} disagree "
          f"({disagree / max(len(closed), 1) * 100:.1f}%)")
    print(f"  trades        {len(trades)}   barrier {n}")
    print(f"  median stop   {np.median(stops):.2f} pt   median mult {np.median(mults):.2f}")
    print(f"  win rate      {wr * 100:.2f}")
    print(f"  edge          {e.mean():+.2f}  sd {e.std():.2f}  P(>0) {100 * (e > 0).mean():.0f}%")
    print(f"  economic bar  {bar:+.2f}   statistical hurdle (3 se) {stat_hurdle:+.2f}")
    print(f"  binding       {'statistical' if stat_hurdle > bar else 'economic'}")
    print(f"  gross ${sum(t.get('gross_pnl') or 0 for t in trades):>11,.0f}   "
          f"net ${sum(t.get('pnl_dollars') or 0 for t in trades):>11,.0f}")
