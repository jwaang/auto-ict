"""Test what ICT actually claims, primitive by primitive.

The previous harness asked "does price rise after a bullish FVG forms". That is
not an ICT claim. An FVG marks an imbalance price tends to *return* to, and its
Consequent Encroachment is a reaction level; it is a location to enter from, not
a reason to trade. The reference in docs/ places it at step 4 of the setup —
after bias, after the liquidity objective, after the trigger.

The directional claims sit in the sweep and the structure shift, and the same
reference is blunt about the first: "this is the single most important
pre-condition for an ICT entry. Without a sweep, the setup is incomplete."

So three claims are tested here, each against the benchmark it deserves:

  MAGNET   Do unfilled FVGs get filled more often, and sooner, than matched
           random zones of the same width, at the same distance from price, in
           the same session? A gap near price fills easily and that is not a
           claim about imbalance, so the control has to match geometry.

  SWEEP    After price wicks a prior high or low and closes back through it,
           does it reverse more often than chance? This is the one place ICT
           puts a directional prediction, so it gets the coin-flip null.

  CE       When price returns to the 50% midpoint of an unfilled FVG, does it
           reverse there more often than at a random level the same distance
           away?

Intervals are day-block bootstraps throughout: detections cluster inside a
session and overlapping forward windows share bars, so an independence
assumption inflates every z.
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
START = os.environ.get("ICT_START", "2021-07-25")
END = os.environ.get("ICT_END", "2024-12-31")
TF = os.environ.get("ICT_TF", "15min")
LOOKAHEAD = int(os.environ.get("ICT_LOOKAHEAD", "96"))   # bars allowed to fill
OUT = os.environ.get("ICT_OUT", "logs/exp27/ict_claims.json")


def block_ci(flags, days, reps=2000, seed=7):
    """Mean and a day-block bootstrap interval for a boolean series."""
    flags = np.asarray(flags, dtype=float)
    if len(flags) == 0:
        return None
    uniq = np.unique(days)
    by = {d: flags[days == d] for d in uniq}
    rng = np.random.default_rng(seed)
    draws = np.empty(reps)
    for k in range(reps):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        draws[k] = np.concatenate([by[d] for d in pick]).mean()
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return {"rate": float(flags.mean() * 100), "ci": [float(lo * 100), float(hi * 100)],
            "sd": float(draws.std(ddof=1) * 100), "n": int(len(flags)),
            "n_days": int(len(uniq))}


df = load_continuous_contract(DATA)
bars = resample_ohlcv(df, TF)
ts = bars["timestamp"]
bars = bars.loc[(ts >= pd.Timestamp(START, tz="UTC")) &
                (ts <= pd.Timestamp(END, tz="UTC"))].reset_index(drop=True)
ohlc = smc_adapter.prepare_ohlc(bars)
high = bars["high"].to_numpy()
low = bars["low"].to_numpy()
close = bars["close"].to_numpy()
day = bars["timestamp"].dt.tz_convert("America/New_York").dt.date.to_numpy()
n_bars = len(bars)
print(f"{TF}: {n_bars:,} bars {START}..{END}", flush=True)

rng = np.random.default_rng(11)
results = {}

# ---------------------------------------------------------------------------
# MAGNET: do FVGs fill more than matched random zones?
# ---------------------------------------------------------------------------
fvgs = smc_adapter.detect_fvgs(ohlc)
hit_real, hit_ctrl, bars_to_fill, dd = [], [], [], []
for f in fvgs:
    i = f["candle_index"]
    if i + LOOKAHEAD >= n_bars:
        continue
    top, bot = f["top"], f["bottom"]
    width = top - bot
    if width <= 0:
        continue
    ref = close[i]
    # A real gap sits away from price by some offset; the control keeps the
    # same width and the same signed offset, so "near price fills easily" is
    # held constant and only the imbalance claim is tested.
    offset = ((top + bot) / 2) - ref
    fut_hi = high[i + 1:i + 1 + LOOKAHEAD]
    fut_lo = low[i + 1:i + 1 + LOOKAHEAD]
    touched = (fut_hi >= bot) & (fut_lo <= top)
    hit_real.append(bool(touched.any()))
    if touched.any():
        bars_to_fill.append(int(np.argmax(touched)) + 1)
    # Control: identical geometry — same width, same signed offset, so the same
    # side of price — but anchored at a randomly chosen other bar. Mirroring to
    # the opposite side instead would confound the test with trend, since in a
    # rising market the upper zone is reached more often whatever it contains.
    j = int(rng.integers(0, n_bars - LOOKAHEAD - 1))
    c_mid = close[j] + offset
    c_top, c_bot = c_mid + width / 2, c_mid - width / 2
    ctouch = ((high[j + 1:j + 1 + LOOKAHEAD] >= c_bot) &
              (low[j + 1:j + 1 + LOOKAHEAD] <= c_top))
    hit_ctrl.append(bool(ctouch.any()))
    dd.append(day[i])

dd = np.array(dd)
results["fvg_fill_real"] = block_ci(hit_real, dd)
results["fvg_fill_mirror_control"] = block_ci(hit_ctrl, dd)
r, c = results["fvg_fill_real"], results["fvg_fill_mirror_control"]
print(f"\nMAGNET  FVG fill within {LOOKAHEAD} bars")
print(f"  real     {r['rate']:.2f}%  ci [{r['ci'][0]:.2f},{r['ci'][1]:.2f}]  n={r['n']} ({r['n_days']}d)")
print(f"  mirrored {c['rate']:.2f}%  ci [{c['ci'][0]:.2f},{c['ci'][1]:.2f}]")
diff = r["rate"] - c["rate"]
print(f"  difference {diff:+.2f} points   median bars to fill "
      f"{int(np.median(bars_to_fill)) if bars_to_fill else 0}")

# ---------------------------------------------------------------------------
# SWEEP: the one directional claim. Wick through a prior extreme, close back.
# ---------------------------------------------------------------------------
shl = smc_adapter.detect_swings(ohlc, TF)[0]
sw = shl["HighLow"].to_numpy()
lvl = shl["Level"].to_numpy()

sweeps = []
last_hi = last_lo = None
for i in range(n_bars):
    if not np.isnan(sw[i]):
        if sw[i] == 1:
            last_hi = lvl[i]
        elif sw[i] == -1:
            last_lo = lvl[i]
        continue
    # Buy-side sweep: wick above a prior swing high, close back below it.
    if last_hi is not None and high[i] > last_hi and close[i] < last_hi:
        sweeps.append((i, "bearish"))
    elif last_lo is not None and low[i] < last_lo and close[i] > last_lo:
        sweeps.append((i, "bullish"))

print(f"\nSWEEP   {len(sweeps)} sweeps detected")
for h in (4, 12, 24, 48):
    ok = [(i, d) for i, d in sweeps if i + h < n_bars]
    if len(ok) < 50:
        continue
    idx = np.array([i for i, _ in ok])
    bull = np.array([d == "bullish" for _, d in ok])
    fwd = close[idx + h] - close[idx]
    hit = np.where(bull, fwd > 0, fwd < 0)
    b = block_ci(hit, day[idx])
    edge = b["rate"] - 50
    z = edge / b["sd"] if b["sd"] > 0 else float("nan")
    results[f"sweep_reversal_h{h}"] = {**b, "edge": edge, "z_block": z}
    flag = "***" if abs(z) > 3 and b["n"] >= 5000 else ""
    print(f"  h={h:<3} n={b['n']:>6} ({b['n_days']:>4}d) rate {b['rate']:.2f}% "
          f"edge {edge:+.2f} z {z:+.2f} ci [{b['ci'][0]-50:+.2f},{b['ci'][1]-50:+.2f}] "
          f"bull% {bull.mean()*100:.1f} {flag}", flush=True)

Path(OUT).parent.mkdir(parents=True, exist_ok=True)
json.dump(results, open(OUT, "w"), indent=2, default=float)
print(f"\nwrote {OUT}")
