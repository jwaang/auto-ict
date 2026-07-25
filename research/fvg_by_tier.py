"""Experiments 36 and 37, split by FVG strength tier.

Both were run on all 43,536 gaps pooled. The source says weak gaps are traps to
be discarded and exceptional ones produce a reaction that is "almost always
violent and immediate", so pooling averages the category to throw away with the
category to trade. If the tiers behave differently, neither published number
describes anything real.

Two measurements per tier, the same as the pooled versions:

  MAGNET    does the gap get filled more than a geometry-matched control zone?
  REACTION  given price returned, does it continue in the gap's direction more
            than from a matched control zone price also returned to?

Pooled results being reproduced: magnet +4.30 points (z +15.05) at a 48-bar
lookahead; reaction −0.84 at h=4, never above 50% in absolute terms.
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
from research.fvg_quality import EXCEPTIONAL, QUIETLY_STRONG, WEAK, classify_all

DATA = "historical/ES-5y/glbx-mdp3-20210724-20260723.ohlcv-1m.dbn.zst"
START = os.environ.get("FQ_START", "2021-07-25")
END = os.environ.get("FQ_END", "2024-12-31")
TF = os.environ.get("FQ_TF", "5min")
WAIT = 48
HORIZONS = [1, 4, 12]
OUT = os.environ.get("FQ_OUT", "logs/exp27/fvg_by_tier_disp.json")

df = load_continuous_contract(DATA)
bars = resample_ohlcv(df, TF)
ts = bars["timestamp"]
bars = bars.loc[(ts >= pd.Timestamp(START, tz="UTC")) &
                (ts <= pd.Timestamp(END, tz="UTC"))].reset_index(drop=True)
ohlc = smc_adapter.prepare_ohlc(bars)
high, low, close = (bars[c].to_numpy() for c in ("high", "low", "close"))
day = bars["timestamp"].dt.tz_convert("America/New_York").dt.date.to_numpy()
n = len(bars)
rng = np.random.default_rng(5)

fvgs = smc_adapter.detect_fvgs(ohlc)
disp = detect_displacements(bars)
disp_idx = {d["candle_index"] for d in disp}
tiers = classify_all(fvgs, high, low, disp_idx)
print(f"{len(disp)} displacement bars ({len(disp)/n*100:.1f}% of frame)")
print(f"{TF}: {n:,} bars {START}..{END}")
print(f"{len(fvgs)} FVGs -> " + "  ".join(
    f"{k} {len(v)} ({len(v)/len(fvgs)*100:.1f}%)" for k, v in tiers.items()))


def block(v, d, reps=1500):
    v = np.asarray(v, dtype=float)
    if len(v) == 0:
        return float("nan"), float("nan")
    uniq = np.unique(d)
    by = {k: v[d == k] for k in uniq}
    draws = np.empty(reps)
    for k in range(reps):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        draws[k] = np.concatenate([by[x] for x in pick]).mean()
    return float(v.mean()), float(draws.std(ddof=1))


def touch(i, top, bot, limit):
    hi, lo = high[i + 1:i + 1 + limit], low[i + 1:i + 1 + limit]
    t = (hi >= bot) & (lo <= top)
    return i + 1 + int(np.argmax(t)) if t.any() else None


results = {}
for tier in (WEAK, QUIETLY_STRONG, EXCEPTIONAL):
    group = tiers[tier]
    fill_r, fill_c, dfill = [], [], []
    react = {h: ([], [], [], []) for h in HORIZONS}   # real, ctrl, dreal, dctrl
    for f in group:
        i = f["candle_index"]
        top, bot = f["top"], f["bottom"]
        w = top - bot
        if w <= 0 or i + WAIT + max(HORIZONS) >= n:
            continue
        sign = 1.0 if f["type"] == "bullish" else -1.0
        offset = (top + bot) / 2 - close[i]

        r = touch(i, top, bot, WAIT)
        fill_r.append(r is not None)
        dfill.append(day[i])

        j = int(rng.integers(0, n - WAIT - max(HORIZONS) - 1))
        cm = close[j] + offset
        ct, cb = cm + w / 2, cm - w / 2
        cr = touch(j, ct, cb, WAIT)
        fill_c.append(cr is not None)

        if r is not None and r + max(HORIZONS) < n:
            for h in HORIZONS:
                react[h][0].append(float((close[r + h] - close[r]) * sign > 0))
                react[h][2].append(day[r])
        if cr is not None and cr + max(HORIZONS) < n:
            for h in HORIZONS:
                react[h][1].append(float((close[cr + h] - close[cr]) * sign > 0))
                react[h][3].append(day[cr])

    if len(fill_r) < 200:
        print(f"\n{tier}: only {len(fill_r)} usable, skipped")
        continue
    fm, fsd = block(fill_r, np.array(dfill))
    cm_, csd = block(fill_c, np.array(dfill))
    diff = (fm - cm_) * 100
    sd = float(np.sqrt(fsd ** 2 + csd ** 2)) * 100
    print(f"\n=== {tier}  n={len(fill_r)} ===")
    print(f"  MAGNET   fill {fm*100:.2f}%  control {cm_*100:.2f}%  "
          f"diff {diff:+.2f}  z {diff/sd if sd>0 else float('nan'):+.2f}")
    results[f"{tier}_magnet"] = {"n": len(fill_r), "fill": fm * 100,
                                 "ctrl": cm_ * 100, "diff": diff,
                                 "z": diff / sd if sd > 0 else None}

    for h in HORIZONS:
        rr, cc, dr, dc = react[h]
        if len(rr) < 200 or len(cc) < 200:
            continue
        rm, rsd = block(rr, np.array(dr))
        km, ksd = block(cc, np.array(dc))
        d2 = (rm - km) * 100
        s2 = float(np.sqrt(rsd ** 2 + ksd ** 2)) * 100
        z2 = d2 / s2 if s2 > 0 else float("nan")
        flag = "***" if abs(z2) > 3 and len(rr) >= 5000 else ""
        print(f"  REACTION h={h:<3} n={len(rr):>6} cont {rm*100:>6.2f}%  "
              f"control {km*100:>6.2f}%  diff {d2:+6.2f}  z {z2:+6.2f} {flag}")
        results[f"{tier}_reaction_h{h}"] = {"n": len(rr), "cont": rm * 100,
                                            "ctrl": km * 100, "diff": d2, "z": z2}

Path(OUT).parent.mkdir(parents=True, exist_ok=True)
json.dump(results, open(OUT, "w"), indent=2, default=float)
print(f"\nwrote {OUT}")
