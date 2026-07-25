"""PD arrays: given price returned to the zone, does it react in the zone's direction?

This is the test the reference calls for and the one previously skipped. An FVG
claim has two parts — price retraces into the gap, *and then continues in the
gap's direction*. Part one is confirmed (+4.30 points of fill rate over a
matched control, z +15.05). Part two is the tradeable half.

The trigger is the RETURN, not the formation, so every measurement here starts
at the bar price re-enters the zone. The control is a geometry-matched zone,
same width and same signed offset, anchored at a random other bar, and it is
only counted when price returned to *it* as well — otherwise the comparison
measures "does price come back" rather than "does this zone work".

CE is tested inside the same pass: the reference says the 50% midpoint is the
highest-probability reaction point *within* the gap, so the control for that
claim is the rest of the gap rather than a different gap.
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

DATA = "historical/ES-5y/glbx-mdp3-20210724-20260723.ohlcv-1m.dbn.zst"
START = os.environ.get("PD_START", "2021-07-25")
END = os.environ.get("PD_END", "2024-12-31")
TF = os.environ.get("PD_TF", "5min")
WAIT = int(os.environ.get("PD_WAIT", "96"))      # bars allowed for the return
HORIZONS = [1, 2, 4, 6, 12, 24]
OUT = os.environ.get("PD_OUT", "logs/exp27/pd_reaction.json")

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
print(f"{TF}: {n:,} bars {START}..{END}", flush=True)


def first_return(i, top, bot, limit):
    """Index of the first bar after i whose range touches the zone."""
    hi = high[i + 1:i + 1 + limit]
    lo = low[i + 1:i + 1 + limit]
    t = (hi >= bot) & (lo <= top)
    return i + 1 + int(np.argmax(t)) if t.any() else None


def block_ci(v, d, reps=2000):
    v = np.asarray(v, dtype=float)
    uniq = np.unique(d)
    by = {k: v[d == k] for k in uniq}
    draws = np.empty(reps)
    for k in range(reps):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        draws[k] = np.concatenate([by[x] for x in pick]).mean()
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return float(v.mean()), float(lo), float(hi), float(draws.std(ddof=1))


fvgs = smc_adapter.detect_fvgs(ohlc)
real = {h: [] for h in HORIZONS}
ctrl = {h: [] for h in HORIZONS}
dreal = {h: [] for h in HORIZONS}
dctrl = {h: [] for h in HORIZONS}
deep_ce, deep_shallow = {h: [] for h in HORIZONS}, {h: [] for h in HORIZONS}
n_ret = n_ctrl_ret = 0

for f in fvgs:
    i = f["candle_index"]
    top, bot = f["top"], f["bottom"]
    width = top - bot
    if width <= 0 or i + WAIT + max(HORIZONS) >= n:
        continue
    sign = 1.0 if f["type"] == "bullish" else -1.0
    ce = (top + bot) / 2

    r = first_return(i, top, bot, WAIT)
    if r is not None and r + max(HORIZONS) < n:
        n_ret += 1
        # Did the return reach the midpoint, or only the near edge?
        reached_ce = (high[r] >= ce) and (low[r] <= ce)
        for h in HORIZONS:
            v = float((close[r + h] - close[r]) * sign > 0)
            real[h].append(v)
            dreal[h].append(day[r])
            (deep_ce if reached_ce else deep_shallow)[h].append(v)

    # Control: same width, same signed offset from price, different time.
    offset = ce - close[i]
    j = int(rng.integers(0, n - WAIT - max(HORIZONS) - 1))
    c_mid = close[j] + offset
    c_top, c_bot = c_mid + width / 2, c_mid - width / 2
    cr = first_return(j, c_top, c_bot, WAIT)
    if cr is not None and cr + max(HORIZONS) < n:
        n_ctrl_ret += 1
        for h in HORIZONS:
            ctrl[h].append(float((close[cr + h] - close[cr]) * sign > 0))
            dctrl[h].append(day[cr])

print(f"FVGs {len(fvgs)}   returned to zone: real {n_ret}, control {n_ctrl_ret}\n")
print(f"{'h':>3} {'n':>7} {'real%':>7} {'ctrl%':>7} {'diff':>7} {'ci_lo':>7} "
      f"{'ci_hi':>7} {'z':>7}   {'CE%':>7} {'edge%':>7} {'ce-edge':>8}")
res = {}
for h in HORIZONS:
    if len(real[h]) < 200 or len(ctrl[h]) < 200:
        continue
    rm, _, _, rsd = block_ci(real[h], np.array(dreal[h]))
    cm, _, _, csd = block_ci(ctrl[h], np.array(dctrl[h]))
    diff = (rm - cm) * 100
    sd = float(np.sqrt(rsd ** 2 + csd ** 2)) * 100
    lo, hi = diff - 1.96 * sd, diff + 1.96 * sd
    z = diff / sd if sd > 0 else float("nan")
    ce_m = np.mean(deep_ce[h]) * 100 if len(deep_ce[h]) >= 200 else float("nan")
    sh_m = np.mean(deep_shallow[h]) * 100 if len(deep_shallow[h]) >= 200 else float("nan")
    res[h] = {"n": len(real[h]), "real": rm * 100, "ctrl": cm * 100, "diff": diff,
              "ci": [lo, hi], "z": z, "ce": ce_m, "edge_only": sh_m}
    flag = "***" if abs(z) > 3 and len(real[h]) >= 5000 else ""
    print(f"{h:>3} {len(real[h]):>7} {rm*100:>7.2f} {cm*100:>7.2f} {diff:>+7.2f} "
          f"{lo:>+7.2f} {hi:>+7.2f} {z:>+7.2f}   {ce_m:>7.2f} {sh_m:>7.2f} "
          f"{ce_m-sh_m:>+8.2f} {flag}", flush=True)

Path(OUT).parent.mkdir(parents=True, exist_ok=True)
json.dump(res, open(OUT, "w"), indent=2, default=float)
print(f"\nreal% = continuation in the gap direction after price returned to it")
print(f"CE% vs edge% = returns that reached the 50% midpoint vs only the near edge")
print(f"wrote {OUT}")
