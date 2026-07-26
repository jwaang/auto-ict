"""Does the OTE band peak, or does depth just mean room to run?

ICT claims 61.8-79% is the highest-probability retracement entry, so the claim
predicts a **peak** in that band. A monotone rise with depth refutes the zone
while explaining the belief: price that has retraced further has more of the leg
left to travel.

Every sample is taken at the bar a band is **first reached**, after the leg's
confirmation — see `research/depth_claims.py` for why both matter.
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
from research.depth_claims import BANDS, first_touch_by_band

DATA = "historical/ES-5y/glbx-mdp3-20210724-20260723.ohlcv-1m.dbn.zst"
_SEEN = set()


def env(name, default):
    _SEEN.add(name)
    return os.environ.get(name, default)


START = env("OTE_START", "2021-07-25")
END = env("OTE_END", "2024-12-31")
TF = env("OTE_TF", "5min")
LIMIT = int(env("OTE_LIMIT", "96"))
REQUIRE_DISP = env("OTE_DISP", "1") == "1"
OUT = env("OTE_OUT", "logs/exp27/ote.json")
HORIZONS = [4, 12, 24]

for k in os.environ:
    if k.startswith("OTE_") and k not in _SEEN:
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

_, swings = smc_adapter.detect_swings(ohlc, TF)
swings = sorted(swings, key=lambda s: s["candle_index"])
disp_idx = {d["candle_index"] for d in detect_displacements(bars, atr_mult=1.0)}
print(f"{TF}: {n:,} bars, {len(swings)} swings, {len(disp_idx)} displacement bars",
      flush=True)

# Legs are consecutive alternating swings. `candle_index` is the confirmation
# bar, so the leg is knowable only from the later of the two.
legs, skipped_no_disp = [], 0
for a, b in zip(swings, swings[1:]):
    if a["type"] == b["type"]:
        continue
    bullish = b["type"] == "swing_high"
    start, end = a["level"], b["level"]
    if (end - start) * (1 if bullish else -1) <= 0:
        continue
    if REQUIRE_DISP:
        # The source: OTE is valid only after displacement.
        span = range(a["candle_index"], b["candle_index"] + 1)
        if not any(i in disp_idx for i in span):
            skipped_no_disp += 1
            continue
    legs.append((start, end, b["candle_index"], bullish))

print(f"{len(legs)} legs ({skipped_no_disp} dropped for no displacement)", flush=True)


def block(v, d, reps=1500):
    v = np.asarray(v, dtype=float)
    uniq = np.unique(d)
    by = {k: v[d == k] for k in uniq}
    draws = np.empty(reps)
    for k in range(reps):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        draws[k] = np.concatenate([by[x] for x in pick]).mean()
    return float(v.mean()), float(draws.std(ddof=1))


samples = {name: {h: ([], []) for h in HORIZONS} for name, _, _ in BANDS}
for start, end, confirm, bullish in legs:
    touched = first_touch_by_band(high, low, start, end, confirm, LIMIT, n)
    sign = 1.0 if bullish else -1.0
    for band, k in touched.items():
        for h in HORIZONS:
            if k + h >= n:
                continue
            fwd = close[k + h] - close[k]
            if fwd == 0:                       # ties excluded, never assigned
                continue
            vals, days = samples[band][h]
            vals.append(float(fwd * sign > 0))
            days.append(day[k])

print(f"\n{'band':>14} " + "  ".join(f"{'h'+str(h):>16}" for h in HORIZONS))
results = {}
for name, _, _ in BANDS:
    line = f"{name:>14} "
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
print("\nICT predicts a PEAK in the 61.8-79 band. A monotone curve refutes the")
print("zone: deeper retracements simply have more of the leg left to travel.")
print(f"wrote {OUT}")
