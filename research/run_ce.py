"""Is the 50% midpoint of a gap special, or is CE the same artifact as OTE?

Consequent encroachment claims the 50% level of a fair value gap is the
highest-probability reaction point *within* it — a zone inside a range, exactly
the shape of claim experiment 45 found untrue for OTE, where continuation rose
monotonically with depth and the 61.8-79 band was no peak.

So this is a second, independent test of whether ICT's zone concept is a category
error. Two monotone curves would be a general finding about the methodology
rather than two separate nulls.

It cannot rescue the FVG entry either way: experiment 37 already refuted the
reaction against a matched control. The narrower question here is whether, inside
a zone that does not work, one depth is less bad than the others.

Every sample is taken at the bar a level is **first reached**. The gap is
knowable once its third candle closes, and `candle_index` points at that bar, so
measurement starts the bar after — no confirmation lag to subtract, unlike swings.
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.historical import load_continuous_contract, resample_ohlcv
from ict import smc_adapter
from ict.displacement import detect_displacements
from research.depth_claims import GAP_LEVELS, first_touch_by_level

DATA = "historical/ES-5y/glbx-mdp3-20210724-20260723.ohlcv-1m.dbn.zst"
_SEEN = set()


def env(name, default):
    _SEEN.add(name)
    return os.environ.get(name, default)


START = env("CE_START", "2021-07-25")
END = env("CE_END", "2024-12-31")
TF = env("CE_TF", "5min")
LIMIT = int(env("CE_LIMIT", "96"))

OUT = env("CE_OUT", "logs/exp27/ce.json")
HORIZONS = [4, 12, 24]

for k in os.environ:
    if k.startswith("CE_") and k not in _SEEN:
        raise SystemExit(f"{k} was set but is not read by this script")

df = load_continuous_contract(DATA)
bars = resample_ohlcv(df, TF) if TF != "1min" else df.copy()
ts = bars["timestamp"]
bars = bars.loc[(ts >= pd.Timestamp(START, tz="UTC")) &
                (ts <= pd.Timestamp(END, tz="UTC"))].reset_index(drop=True)
ohlc = smc_adapter.prepare_ohlc(bars)
high, low, close = (bars[c].to_numpy() for c in ("high", "low", "close"))
day = bars["timestamp"].dt.tz_convert("America/New_York").dt.date.to_numpy()
n = len(bars)
rng = np.random.default_rng(21)

fvgs = smc_adapter.detect_fvgs(ohlc)
print(f"{TF}: {n:,} bars, {len(fvgs)} fair value gaps", flush=True)


def block(v, d, reps=1500):
    v = np.asarray(v, dtype=float)
    uniq = np.unique(d)
    by = {k: v[d == k] for k in uniq}
    draws = np.empty(reps)
    for k in range(reps):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        draws[k] = np.concatenate([by[x] for x in pick]).mean()
    return float(v.mean()), float(draws.std(ddof=1))


samples = {name: {h: ([], []) for h in HORIZONS} for name, _ in GAP_LEVELS}
for f in fvgs:
    i = f["candle_index"]
    top, bot = f["top"], f["bottom"]
    if top <= bot or i + 1 >= n:
        continue
    bullish = f["type"] == "bullish"
    sign = 1.0 if bullish else -1.0
    touched = first_touch_by_level(high, low, top, bot, bullish, i, LIMIT, n)
    for level, k in touched.items():
        for h in HORIZONS:
            if k + h >= n:
                continue
            fwd = close[k + h] - close[k]
            if fwd == 0:                       # ties excluded, never assigned
                continue
            vals, days = samples[level][h]
            vals.append(float(fwd * sign > 0))
            days.append(day[k])

print(f"\n{'level':>12} " + "  ".join(f"{'h'+str(h):>16}" for h in HORIZONS))
results = {}
for name, _ in GAP_LEVELS:
    line = f"{name:>12} "
    for h in HORIZONS:
        vals, days = samples[name][h]
        if len(vals) < 200:
            line += f"{'n=' + str(len(vals)):>16}  "
            continue
        m, sd = block(vals, np.array(days))
        edge = m * 100 - 50
        z = edge / (sd * 100) if sd > 0 else float("nan")
        star = "*" if abs(z) > 3 and len(vals) >= 5000 else " "
        line += f"{len(vals):>6} {edge:+6.2f}(z{z:+5.1f}){star}"
        results[f"{name}_h{h}"] = {"n": len(vals), "edge": edge, "z": z}
    print(line, flush=True)

Path(OUT).parent.mkdir(parents=True, exist_ok=True)
json.dump(results, open(OUT, "w"), indent=2, default=float)
print("\nCE predicts a PEAK at the 50% level. A monotone curve refutes it and,")
print("with experiment 45, says ICT zones are artifacts of continuous depth.")
print(f"wrote {OUT}")
