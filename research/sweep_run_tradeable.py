"""Is the sweep/run edge tradeable once geometry and costs are applied?

Experiment 40 found the first result to pass the full bar: a failed break (wick
through, close back inside) where daily structure *agrees* with the probed side
continues in that direction — +5.57 points, z 10.24, n=10,108 on 1-minute,
replicated at 5m and 15m. That is a direction count, not money.

Geometry follows the source rather than a parameter grid. The stop goes **beyond
the swept extreme with a buffer**, because the source is explicit that stops at
the level itself "get tagged routinely", and the buffer is expressed in ATR so it
scales with the instrument. The target is a multiple of that risk, standing in
for "the next draw on liquidity" — a real liquidity target would be better and is
the obvious follow-up if this is close.

A previous attempt at this measured the wrong thing: it passed SW_ENTRY to a
script that never read it, and silently re-ran the old population. Every
environment variable here is asserted to have been consumed.
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
from ict.candles import calc_atr

DATA = "historical/ES-5y/glbx-mdp3-20210724-20260723.ohlcv-1m.dbn.zst"
_CONSUMED = set()


def env(name, default):
    _CONSUMED.add(name)
    return os.environ.get(name, default)


START = env("SRT_START", "2021-07-25")
END = env("SRT_END", "2024-12-31")
TF = env("SRT_TF", "5min")
CELL = env("SRT_CELL", "agree_sweep")   # agree_sweep | agree_all | disagree_sweep | all
OUT = env("SRT_OUT", "logs/exp27/sweep_run_tradeable.json")
COST = 1.02
BUFFERS = [0.25, 0.5, 1.0]              # ATR multiples beyond the swept extreme
MULTS = [1.0, 1.5, 2.0, 3.0]

for k in os.environ:
    if k.startswith("SRT_") and k not in _CONSUMED:
        raise SystemExit(f"{k} was set but is not read by this script")

df = load_continuous_contract(DATA)


def daily_bias_by_session():
    daily = resample_ohlcv(df, "1D", session_aligned=True)
    o = smc_adapter.prepare_ohlc(daily)
    _, swings = smc_adapter.detect_swings(o, "bias")
    stamps = daily["timestamp"].to_numpy()
    highs, lows, out, last = [], [], {}, "neutral"
    for s in sorted(swings, key=lambda x: x["candle_index"]):
        (highs if s["type"] == "swing_high" else lows).append(s["level"])
        if len(highs) >= 2 and len(lows) >= 2:
            up = highs[-1] > highs[-2] and lows[-1] > lows[-2]
            dn = highs[-1] < highs[-2] and lows[-1] < lows[-2]
            last = "bullish" if up else "bearish" if dn else "neutral"
        if s["candle_index"] < len(stamps):
            out[pd.Timestamp(stamps[s["candle_index"]])] = last
    return out


bias_at = daily_bias_by_session()
bdays = sorted(bias_at)

bars = resample_ohlcv(df, TF)
ts = bars["timestamp"]
bars = bars.loc[(ts >= pd.Timestamp(START, tz="UTC")) &
                (ts <= pd.Timestamp(END, tz="UTC"))].reset_index(drop=True)
ohlc = smc_adapter.prepare_ohlc(bars)
high, low, close = (bars[c].to_numpy() for c in ("high", "low", "close"))
stamp = bars["timestamp"]
day = stamp.dt.tz_convert("America/New_York").dt.date.to_numpy()
atr = calc_atr(bars).to_numpy()
n = len(bars)

keys = np.array([k.value for k in bdays])
vals = [bias_at[k] for k in bdays]
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
        # Record both extremes of the probe candle. Which one invalidates the
        # trade depends on the direction taken, not on which level was probed.
        events.append((i, "up", "sweep" if close[i] < last_hi else "run",
                       high[i], low[i]))
    elif last_lo is not None and low[i] < last_lo:
        events.append((i, "down", "sweep" if close[i] > last_lo else "run",
                       low[i], high[i]))


def keep(e):
    i, d, form = e[0], e[1], e[2]
    agrees = ((d == "up" and bias_per_bar[i] == "bullish") or
              (d == "down" and bias_per_bar[i] == "bearish"))
    if CELL == "agree_sweep":
        return agrees and form == "sweep"
    if CELL == "agree_all":
        return agrees
    if CELL == "disagree_sweep":
        return (not agrees and bias_per_bar[i] != "neutral") and form == "sweep"
    return True


rows = [e for e in events if keep(e)]
print(f"{TF} {START}..{END}  cell={CELL}  {len(events)} events -> {len(rows)} selected",
      flush=True)

intrabar = Intrabar(df)
minute_close = df.set_index("timestamp")["close"]


def close_at(t):
    k = minute_close.index.searchsorted(t, side="right") - 1
    return float(minute_close.iloc[k]) if k >= 0 else None


rng = np.random.default_rng(4)


def block(v, d, reps=1500):
    v = np.asarray(v, dtype=float)
    uniq = np.unique(d)
    by = {k: v[d == k] for k in uniq}
    draws = np.empty(reps)
    for k in range(reps):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        draws[k] = np.concatenate([by[x] for x in pick]).mean()
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return float(v.mean()), float(lo), float(hi)


out_rows = []
print(f"\n{'buf':>5} {'mult':>5} {'n':>6} {'medR':>7} {'meanR':>9} {'ci_lo':>9} {'ci_hi':>9}")
for buf in BUFFERS:
    for m in MULTS:
        rs, dd = [], []
        for i, d, form, probed, opposite in rows:
            if np.isnan(atr[i]) or atr[i] <= 0:
                continue
            # Continuation trade: the probe direction is the trade direction.
            direction = "LONG" if d == "up" else "SHORT"
            sign = 1.0 if d == "up" else -1.0
            entry = close[i]
            # The stop goes beyond the candle extreme that would invalidate THIS
            # trade, which for a continuation is the far side of the probe
            # candle — not the level that was probed. "Stop beyond the swept
            # extreme" is the rule for the reversal trade, where the probed high
            # sits above a short entry. Applying it to a long put the stop above
            # the entry and produced impossible mean R of -3 to -6.
            stop = opposite - sign * buf * atr[i]
            risk = abs(entry - stop)
            if risk <= 0:
                continue
            target = entry + sign * risk * m
            t0 = stamp.iloc[i]
            res = intrabar.first_touch(t0, session_end(t0), direction, stop, target)
            cost = COST / risk
            if res == "TP_HIT":
                r = m - cost
            elif res == "SL_HIT":
                r = -1.0 - cost
            else:
                px = close_at(session_end(t0))
                if px is None:
                    continue
                r = (px - entry) * sign / risk - cost
            rs.append(r)
            dd.append(day[i])
        if len(rs) < 200:
            continue
        mean, lo, hi = block(rs, np.array(dd))
        med_risk = float(np.median(
            [abs(close[i] - (opp - (1 if d == "up" else -1) * buf * atr[i]))
             for i, d, _, _, opp in rows[:500] if not np.isnan(atr[i])]))
        out_rows.append({"buffer_atr": buf, "mult": m, "n": len(rs),
                         "median_risk_pts": med_risk, "mean_r": mean, "ci": [lo, hi]})
        flag = "***" if lo > 0 else ""
        print(f"{buf:>5} {m:>5} {len(rs):>6} {med_risk:>7.2f} {mean:>+9.4f} "
              f"{lo:>+9.4f} {hi:>+9.4f} {flag}", flush=True)

Path(OUT).parent.mkdir(parents=True, exist_ok=True)
json.dump(out_rows, open(OUT, "w"), indent=2)
if out_rows:
    best = max(out_rows, key=lambda r: r["mean_r"])
    print(f"\nbest of {len(out_rows)}: {best}")
print("Tradeable requires mean net R > 0 with the interval clear of zero.")
print(f"wrote {OUT}")
