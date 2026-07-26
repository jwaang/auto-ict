"""Does ICT's prescribed entry change the path statistics?

Experiment 41 showed the sweep/run edge is an *endpoint* edge: +5.57 points of
directional accuracy converts to about +0.03R gross, because barrier outcomes
depend on the order levels are touched rather than where the series ends.

Every measurement so far entered at the probe bar, which the source explicitly
calls not a trade. The prescribed entry is sweep -> lower-timeframe MSS confirms
-> enter on the retest of the PD array created by the displacement leg. That is a
**path intervention**: it moves the entry price relative to a fixed invalidation
level, so it changes R:R directly rather than changing direction accuracy.

Three arms, identical stop, so they differ only in entry:

  A  enter at the probe bar close        — closest to the stop, unconfirmed
  B  enter at the MSS confirmation close — furthest from the stop, confirmed
  C  enter on the PD array retest        — between, confirmed, and may never fill

A -> B measures whether confirmation helps. B -> C measures whether the retest
price helps. **Fill rate is reported for every arm**, because waiting misses the
trades that ran away and those are disproportionately winners — reporting only
the survivors is the survivorship error this log already made once.

Targets are R multiples here, held constant across arms on purpose. The source
specifies the next draw on liquidity, which is a better target but would vary by
arm and confound the comparison; it belongs in a separate run.
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
from ict.displacement import detect_displacements
from research.ict_mss import detect_mss, first_mss_after

DATA = "historical/ES-5y/glbx-mdp3-20210724-20260723.ohlcv-1m.dbn.zst"
_SEEN = set()


def env(name, default):
    _SEEN.add(name)
    return os.environ.get(name, default)


START = env("EM_START", "2021-07-25")
END = env("EM_END", "2024-12-31")
TF = env("EM_TF", "15min")
CELL = env("EM_CELL", "agree_all")
MSS_WITHIN = int(env("EM_MSS_WITHIN", "12"))    # bars for the shift to confirm
RETEST_WITHIN = int(env("EM_RETEST_WITHIN", "12"))
BUFFER = float(env("EM_BUFFER", "1.0"))         # ATR beyond the invalidating extreme
# The source says the MSS candle "ideally creates a fair value gap", which is an
# ambiguity in the specification rather than a free parameter. Every threshold is
# reported; picking the one that looks best is the selection trap that has
# already cost two headlines here.
DISP_MULT = float(env("EM_DISP_MULT", "2.0"))
OUT = env("EM_OUT", "logs/exp27/entry_models.json")
COST = 1.02
MULTS = [1.0, 1.5, 2.0, 3.0]

for k in os.environ:
    if k.startswith("EM_") and k not in _SEEN:
        raise SystemExit(f"{k} was set but is not read by this script")

df = load_continuous_contract(DATA)


def daily_bias():
    daily = resample_ohlcv(df, "1D", session_aligned=True)
    o = smc_adapter.prepare_ohlc(daily)
    _, swings = smc_adapter.detect_swings(o, "bias")
    stamps = daily["timestamp"].to_numpy()
    hs, ls, out, last = [], [], {}, "neutral"
    for s in sorted(swings, key=lambda x: x["candle_index"]):
        (hs if s["type"] == "swing_high" else ls).append(s["level"])
        if len(hs) >= 2 and len(ls) >= 2:
            up = hs[-1] > hs[-2] and ls[-1] > ls[-2]
            dn = hs[-1] < hs[-2] and ls[-1] < ls[-2]
            last = "bullish" if up else "bearish" if dn else "neutral"
        if s["candle_index"] < len(stamps):
            out[pd.Timestamp(stamps[s["candle_index"]])] = last
    return out


bias_at = daily_bias()
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

shl, swings = smc_adapter.detect_swings(ohlc, TF)
sw, lvl = shl["HighLow"].to_numpy(), shl["Level"].to_numpy()
disp_idx = {d["candle_index"] for d in detect_displacements(bars, atr_mult=DISP_MULT)}
mss_list = detect_mss(bars, swings, disp_idx)
fvgs = smc_adapter.detect_fvgs(ohlc)
fvg_by_idx = {f["candle_index"]: f for f in fvgs}
print(f"{TF} {START}..{END}: {n:,} bars, {len(mss_list)} MSS "
      f"(disp_mult={DISP_MULT}), {len(fvgs)} FVGs", flush=True)

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
        events.append((i, "up", "sweep" if close[i] < last_hi else "run", low[i]))
    elif last_lo is not None and low[i] < last_lo:
        events.append((i, "down", "sweep" if close[i] > last_lo else "run", high[i]))


def selected(e):
    i, d, form, _ = e
    agrees = ((d == "up" and bias_per_bar[i] == "bullish") or
              (d == "down" and bias_per_bar[i] == "bearish"))
    return agrees if CELL == "agree_all" else (agrees and form == "sweep")


rows = [e for e in events if selected(e)]
print(f"{len(events)} events -> {len(rows)} in cell {CELL}", flush=True)

intrabar = Intrabar(df)
mclose = df.set_index("timestamp")["close"]
rng = np.random.default_rng(6)


def close_at(t):
    k = mclose.index.searchsorted(t, side="right") - 1
    return float(mclose.iloc[k]) if k >= 0 else None


def block(v, d, reps=1500):
    v = np.asarray(v, dtype=float)
    uniq = np.unique(d)
    by = {k: v[d == k] for k in uniq}
    draws = np.empty(reps)
    for k in range(reps):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        draws[k] = np.concatenate([by[x] for x in pick]).mean()
    return float(v.mean()), float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))


def entry_for(arm, i, d):
    """Entry bar index for one arm, or None when the setup never completes."""
    if arm == "A":
        return i
    want = "bullish" if d == "up" else "bearish"
    m = first_mss_after(mss_list, i, want, MSS_WITHIN)
    if m is None:
        return None
    if arm == "B":
        return m["index"]
    # Arm C: the FVG left by the displacement leg, then wait for the retrace.
    f = fvg_by_idx.get(m["index"])
    if f is None:
        return None
    top, bot = f["top"], f["bottom"]
    for k in range(m["index"] + 1, min(m["index"] + 1 + RETEST_WITHIN, n)):
        if high[k] >= bot and low[k] <= top:
            return k
    return None


results = {}
print(f"\n{'arm':>4} {'mult':>5} {'fills':>7} {'fill%':>7} {'medR':>7} "
      f"{'meanR':>9} {'ci_lo':>9} {'ci_hi':>9}")
for arm in ("A", "B", "C"):
    for m in MULTS:
        rs, dd = [], []
        for i, d, form, invalidating in rows:
            if np.isnan(atr[i]) or atr[i] <= 0:
                continue
            j = entry_for(arm, i, d)
            if j is None or j >= n:
                continue
            sign = 1.0 if d == "up" else -1.0
            direction = "LONG" if d == "up" else "SHORT"
            # One stop for all arms: beyond the extreme that invalidates the
            # trade taken, anchored on the original probe candle.
            stop = invalidating - sign * BUFFER * atr[i]
            entry = close[j]
            risk = abs(entry - stop)
            if risk <= 0 or (sign > 0 and entry <= stop) or (sign < 0 and entry >= stop):
                continue
            target = entry + sign * risk * m
            t0 = stamp.iloc[j]
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
        if len(rs) < 100:
            print(f"{arm:>4} {m:>5} {len(rs):>7}   too few")
            continue
        mean, lo, hi = block(rs, np.array(dd))
        fill = len(rs) / max(len(rows), 1) * 100
        results[f"{arm}_m{m}"] = {"arm": arm, "mult": m, "fills": len(rs),
                                  "fill_pct": fill, "mean_r": mean, "ci": [lo, hi]}
        flag = "***" if lo > 0 else ""
        print(f"{arm:>4} {m:>5} {len(rs):>7} {fill:>6.1f}% {np.median(rs):>7.3f} "
              f"{mean:>+9.4f} {lo:>+9.4f} {hi:>+9.4f} {flag}", flush=True)

Path(OUT).parent.mkdir(parents=True, exist_ok=True)
json.dump(results, open(OUT, "w"), indent=2)
print("\nA = probe bar, B = MSS close, C = PD array retest after MSS.")
print("A->B is the value of confirmation; B->C the value of the retest price.")
print(f"wrote {OUT}")
