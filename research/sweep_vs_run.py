"""Liquidity sweep versus liquidity run, split by higher-timeframe bias.

Experiments 34 and 35 measured every wick-through-close-back event with no bias
condition and found continuation 55.3% of the time at z −11.68, then read that as
the methodology being inverted. The distinction never applied is sweep versus
run, and the rule separating them is not mechanical:

    "If the higher-timeframe direction agrees with the side that just got swept,
     expect a run; if it disagrees, expect a sweep."

  sweep  wick through the level, close back inside, limited displacement,
         resolves within 1-3 candles  -> reversal
  run    close beyond the level, sustained displacement, no return
         -> continuation

ES rose across 2021-2024, so higher-timeframe bias was mostly bullish, so most
upward probes were runs — which are supposed to continue. The old test pooled
runs with sweeps and predicted reversal for all of them.

This splits on both axes at once:

  * mechanical form  — did the probe candle close back inside, or beyond?
  * bias agreement   — does daily structure agree with the probed side?

ICT predicts continuation where bias agrees and reversal where it disagrees. The
pooled figure should reappear when the split is collapsed, which is the check
that the only thing that changed is the condition.

Daily bias is the ICT structure reading: rising swing highs *and* rising swing
lows is bullish, falling both is bearish, anything else neutral. Swings come from
the patched detector, so they are confirmed with lag and carry no look-ahead.
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.historical import load_continuous_contract, resample_ohlcv, session_day
from ict import smc_adapter

DATA = "historical/ES-5y/glbx-mdp3-20210724-20260723.ohlcv-1m.dbn.zst"
START = os.environ.get("SR_START", "2021-07-25")
END = os.environ.get("SR_END", "2024-12-31")
TF = os.environ.get("SR_TF", "5min")
HORIZONS = [1, 2, 4, 12, 24]
OUT = os.environ.get("SR_OUT", "logs/exp27/sweep_vs_run.json")

df = load_continuous_contract(DATA)


def daily_bias_by_session() -> dict:
    """Structure direction per CME session day, from confirmed daily swings.

    Bullish needs the last two swing highs rising and the last two swing lows
    rising; bearish needs both falling. Anything else is neutral, which is the
    honest reading rather than forcing a direction.
    """
    daily = resample_ohlcv(df, "1D", session_aligned=True)
    ohlc = smc_adapter.prepare_ohlc(daily)
    _, swings = smc_adapter.detect_swings(ohlc, "bias")
    stamps = daily["timestamp"].to_numpy()

    highs, lows, out = [], [], {}
    last = "neutral"
    for s in sorted(swings, key=lambda x: x["candle_index"]):
        (highs if s["type"] == "swing_high" else lows).append(s["level"])
        if len(highs) >= 2 and len(lows) >= 2:
            up = highs[-1] > highs[-2] and lows[-1] > lows[-2]
            down = highs[-1] < highs[-2] and lows[-1] < lows[-2]
            last = "bullish" if up else "bearish" if down else "neutral"
        idx = s["candle_index"]
        if idx < len(stamps):
            # The reading becomes available at the confirming bar, not before.
            out[pd.Timestamp(stamps[idx])] = last
    return out


bias_at = daily_bias_by_session()
bias_days = sorted(bias_at)
print(f"daily bias readings: {len(bias_days)}", flush=True)

bars = resample_ohlcv(df, TF)
ts = bars["timestamp"]
bars = bars.loc[(ts >= pd.Timestamp(START, tz="UTC")) &
                (ts <= pd.Timestamp(END, tz="UTC"))].reset_index(drop=True)
ohlc = smc_adapter.prepare_ohlc(bars)
high, low, close = (bars[c].to_numpy() for c in ("high", "low", "close"))
stamp = bars["timestamp"]
day = stamp.dt.tz_convert("America/New_York").dt.date.to_numpy()
n = len(bars)

# Most recent bias reading strictly before each bar.
keys = np.array([k.value for k in bias_days])
vals = [bias_at[k] for k in bias_days]
pos = np.searchsorted(keys, stamp.astype("int64").to_numpy(), side="left") - 1
bias_per_bar = np.array([vals[p] if p >= 0 else "neutral" for p in pos])

shl = smc_adapter.detect_swings(ohlc, TF)[0]
sw, lvl = shl["HighLow"].to_numpy(), shl["Level"].to_numpy()

events = []
last_hi = last_lo = None
for i in range(n):
    if not np.isnan(sw[i]):
        if sw[i] == 1:
            last_hi = lvl[i]
        elif sw[i] == -1:
            last_lo = lvl[i]
        continue
    if last_hi is not None and high[i] > last_hi:
        # Probed the buy side, above a prior swing high.
        form = "sweep" if close[i] < last_hi else "run"
        events.append((i, "up", form))
    elif last_lo is not None and low[i] < last_lo:
        form = "sweep" if close[i] > last_lo else "run"
        events.append((i, "down", form))

print(f"{TF}: {n:,} bars, {len(events)} liquidity events", flush=True)

rng = np.random.default_rng(9)


def block(v, d, reps=1500):
    v = np.asarray(v, dtype=float)
    uniq = np.unique(d)
    by = {k: v[d == k] for k in uniq}
    draws = np.empty(reps)
    for k in range(reps):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        draws[k] = np.concatenate([by[x] for x in pick]).mean()
    return float(v.mean()), float(draws.std(ddof=1))


def score(rows, label, expect):
    """`expect` is 'continuation' or 'reversal' — what ICT predicts here."""
    if len(rows) < 200:
        print(f"  {label:34} n={len(rows):>6}  too few")
        return
    idx = np.array([r[0] for r in rows])
    up = np.array([r[1] == "up" for r in rows])
    line = f"  {label:34} n={len(rows):>6}"
    for h in HORIZONS:
        ok = idx + h < n
        if ok.sum() < 200:
            continue
        i2, u2 = idx[ok], up[ok]
        fwd = close[i2 + h] - close[i2]
        # Ties are excluded, not assigned. An exact zero close-to-close change
        # is 6.2% of events at one 5-minute bar, and silently counting them as
        # wins or as failures moves the rate by up to 6 points — which is how
        # experiments 34 and 35 reported a -5.28 that is really -2.33.
        moved = fwd != 0
        i2, u2, fwd = i2[moved], u2[moved], fwd[moved]
        if len(i2) < 200:
            continue
        cont = np.where(u2, fwd > 0, fwd < 0)
        hit = cont if expect == "continuation" else ~cont
        m, sd = block(hit.astype(float), day[i2])
        edge = m * 100 - 50
        z = edge / (sd * 100) if sd > 0 else float("nan")
        star = "*" if abs(z) > 3 and len(i2) >= 5000 else " "
        line += f"   h{h}:{edge:+6.2f}(z{z:+6.2f}){star}"
        results[f"{label}_h{h}"] = {"n": int(len(i2)), "edge": edge, "z": z,
                                    "expect": expect}
    print(line, flush=True)


results = {}
print("\nEdge is measured against what ICT predicts for that cell, so a positive")
print("number means the methodology is right and a negative means it is wrong.\n")

agree = [(i, d, f) for i, d, f in events
         if (d == "up" and bias_per_bar[i] == "bullish")
         or (d == "down" and bias_per_bar[i] == "bearish")]
disagree = [(i, d, f) for i, d, f in events
            if (d == "up" and bias_per_bar[i] == "bearish")
            or (d == "down" and bias_per_bar[i] == "bullish")]
neutral = [(i, d, f) for i, d, f in events if bias_per_bar[i] == "neutral"]

print("BIAS AGREES with the probed side -> ICT expects a RUN (continuation)")
score(agree, "all forms", "continuation")
score([e for e in agree if e[2] == "run"], "closed beyond (run form)", "continuation")
score([e for e in agree if e[2] == "sweep"], "closed back inside (sweep form)", "continuation")

print("\nBIAS DISAGREES -> ICT expects a SWEEP (reversal)")
score(disagree, "all forms", "reversal")
score([e for e in disagree if e[2] == "sweep"], "closed back inside (sweep form)", "reversal")
score([e for e in disagree if e[2] == "run"], "closed beyond (run form)", "reversal")

print("\nNEUTRAL bias (no ICT prediction; shown for completeness)")
score(neutral, "all forms", "reversal")

print("\nCOLLAPSED — reproduces the old pooled test, which predicted reversal")
print("for every close-back-inside event regardless of bias")
score([e for e in events if e[2] == "sweep"], "all sweep-form, any bias", "reversal")

Path(OUT).parent.mkdir(parents=True, exist_ok=True)
json.dump(results, open(OUT, "w"), indent=2, default=float)
print(f"\nwrote {OUT}")
