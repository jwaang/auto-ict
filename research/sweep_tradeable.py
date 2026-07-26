"""Does the sweep-continuation edge survive costs?

Experiment 34 measured a real directional signal: after price wicks a prior
extreme and closes back through it, price continues in the wick direction 55.3%
of the time over the next five minutes, z -11.68, decaying to nothing by two
hours. That is a direction count, not money. This applies geometry and costs.

Entries are taken in the CONTINUATION direction, which is the opposite of what
the methodology says, resolved on 1-minute data through the same first-touch
logic and the same 16:00 ET cutoff as every other measurement here.

The metric is mean net R per trade with a day-block bootstrap interval, because
that is what decides tradeability. Cost is one round turn of spread, slippage
and commission, 1.02 ES points, which at a 3-point stop is 34% of R and at 8
points is 13% — the reason a short-horizon edge is hard to bank.

Twelve geometries are a scan, so the whole grid is reported and the best cell is
read as the best of twelve rather than as a discovery.
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest.intrabar import Intrabar
from backtest.nullmodel import session_end
from data.historical import load_continuous_contract, resample_ohlcv
from ict import smc_adapter

DATA = "historical/ES-5y/glbx-mdp3-20210724-20260723.ohlcv-1m.dbn.zst"
START = os.environ.get("SW_START", "2021-07-25")
END = os.environ.get("SW_END", "2024-12-31")
TF = os.environ.get("SW_TF", "5min")
COST = 1.02
STOPS = [3.0, 5.0, 8.0, 12.0]
MULTS = [0.5, 1.0, 1.5, 2.0]
OUT = os.environ.get("SW_OUT", "logs/exp27/sweep_tradeable.json")

df = load_continuous_contract(DATA)
bars = resample_ohlcv(df, TF)
ts = bars["timestamp"]
bars = bars.loc[(ts >= pd.Timestamp(START, tz="UTC")) &
                (ts <= pd.Timestamp(END, tz="UTC"))].reset_index(drop=True)
ohlc = smc_adapter.prepare_ohlc(bars)
high, low, close = (bars[c].to_numpy() for c in ("high", "low", "close"))
stamp = bars["timestamp"]
day = stamp.dt.tz_convert("America/New_York").dt.date.to_numpy()
n_bars = len(bars)

shl = smc_adapter.detect_swings(ohlc, TF)[0]
sw, lvl = shl["HighLow"].to_numpy(), shl["Level"].to_numpy()

# Continuation direction: a wick above a prior high that closes back below is
# ICT's sell trigger, and the measured effect says price goes UP after it.
sweeps = []
last_hi = last_lo = None
for i in range(n_bars):
    if not np.isnan(sw[i]):
        if sw[i] == 1:
            last_hi = lvl[i]
        elif sw[i] == -1:
            last_lo = lvl[i]
        continue
    if last_hi is not None and high[i] > last_hi and close[i] < last_hi:
        sweeps.append((i, "LONG"))
    elif last_lo is not None and low[i] < last_lo and close[i] > last_lo:
        sweeps.append((i, "SHORT"))

print(f"{TF}: {n_bars:,} bars, {len(sweeps)} sweeps {START}..{END}", flush=True)

intrabar = Intrabar(df)
minute_close = df.set_index("timestamp")["close"]


def close_at(t):
    """Last traded price at or before the cutoff, for a forced close."""
    k = minute_close.index.searchsorted(t, side="right") - 1
    return float(minute_close.iloc[k]) if k >= 0 else None
rng = np.random.default_rng(3)


def block_ci(vals, days, reps=2000):
    vals = np.asarray(vals, dtype=float)
    uniq = np.unique(days)
    by = {d: vals[days == d] for d in uniq}
    draws = np.empty(reps)
    for k in range(reps):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        draws[k] = np.concatenate([by[d] for d in pick]).mean()
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return float(vals.mean()), float(lo), float(hi), float(draws.std(ddof=1))


rows = []
print(f"\n{'stop':>5} {'mult':>5} {'n':>6} {'tp':>5} {'sl':>5} {'cens':>5} "
      f"{'meanR':>8} {'ci_lo':>8} {'ci_hi':>8} {'z':>7}")
for s in STOPS:
    for m in MULTS:
        rs, dd = [], []
        for i, d in sweeps:
            entry = close[i]
            sign = 1.0 if d == "LONG" else -1.0
            stop = entry - sign * s
            target = entry + sign * s * m
            t0 = stamp.iloc[i]
            out = intrabar.first_touch(t0, session_end(t0), d, stop, target)
            cost = COST / s
            if out == "TP_HIT":
                r = m - cost
            elif out == "SL_HIT":
                r = -1.0 - cost
            else:
                px = close_at(session_end(t0))
                if px is None:
                    continue
                r = (px - entry) * sign / s - cost
            rs.append(r)
            dd.append(day[i])
        if len(rs) < 200:
            continue
        mean, lo, hi, sd = block_ci(rs, np.array(dd))
        z = mean / sd if sd > 0 else float("nan")
        rows.append({"stop": s, "mult": m, "n": len(rs), "mean_r": mean,
                     "ci": [lo, hi], "z": z})
        flag = "***" if lo > 0 else ""
        print(f"{s:>5} {m:>5} {len(rs):>6} {'':>5} {'':>5} {'':>5} "
              f"{mean:>+8.4f} {lo:>+8.4f} {hi:>+8.4f} {z:>+7.2f} {flag}", flush=True)

Path(OUT).parent.mkdir(parents=True, exist_ok=True)
json.dump(rows, open(OUT, "w"), indent=2)
best = max(rows, key=lambda r: r["mean_r"]) if rows else None
print(f"\nbest of {len(rows)}: {best}")
print("A positive mean net R with ci_lo > 0 is tradeable; anything else is not.")
print(f"wrote {OUT}")
