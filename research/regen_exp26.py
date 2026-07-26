"""Regenerate experiment 26's trades and save them whole.

Same config as the `concept:full_train` cell: research drawdown, ICT geometry,
all4_majority bias, 15m entries over the training span. The harness stores only
summary rows, so the per-trade records that a stop-width rescore needs have to
be produced again.
"""
import json
import sys
from pathlib import Path
import time

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest import params
from backtest.engine import run_backtest
from backtest.report import calc_stats
from data.historical import load_continuous_contract

DATA = "historical/ES-5y/glbx-mdp3-20210724-20260723.ohlcv-1m.dbn.zst"
OUT = "logs/exp27/exp26_trades.json"

OVERRIDES = {
    "drawdown_limit_pct": 100.0,          # RESEARCH
    "tp_fallback_r": None,                # ICT_GEOMETRY
    "tp_min_r": 0.5,
    "min_rr_ratio": 1.0,
    "bias_vote_rule": "majority",         # BIAS_VARIANTS["all4_majority"]
}

started = time.time()
df = load_continuous_contract(DATA)
print(f"loaded {len(df):,} 1m bars in {time.time()-started:.0f}s", flush=True)

with params.overrides(OVERRIDES):
    result = run_backtest(
        df_1m=df,
        starting_balance=100_000,
        min_score=60,
        ticker="ES",
        entry_tf="15min",
        trade_start=pd.Timestamp("2021-07-25", tz="UTC"),
        trade_end=pd.Timestamp("2024-12-31", tz="UTC"),
        progress_every=10**9,
    )

stats = calc_stats(result)
print(f"trades={len(result.trades)} stats={ {k: stats[k] for k in list(stats)[:6]} }", flush=True)

with open(OUT, "w") as fh:
    json.dump({"overrides": OVERRIDES, "stats": stats, "trades": result.trades},
              fh, indent=2, default=str)
print(f"wrote {OUT} in {time.time()-started:.0f}s", flush=True)
