"""The ICT sequence as specified: 15-minute context, lower-timeframe execution.

Experiment 42 ran the whole sequence on one timeframe and it completed on 1.9% of
setups — 178 samples where 5,000 are needed. That was a consequence of forcing
every leg onto one scale, and it also removed the mechanism: entering and exiting
on the same timeframe cannot produce the large R:R the methodology claims.

The source puts liquidity and bias on 15m and the MSS and entry on 5/3/1m, which
does two things at once. It gives the execution leg roughly fifteen times the
swings and displacements, so the sequence actually completes. And it produces the
geometry — enter with fine precision near the swept extreme, stop beyond that
*coarse* extreme, target the next *coarse* liquidity pool.

The tradeoff, registered before running: a fine entry sits close to the stop, so
risk shrinks and cost/R rises. At 2 points of risk against 1.02 of cost that is
0.51R, and a 3R target then breaks even at a 37.8% win rate. High cost/R is
survivable here only because the target is far — which is why targets are real
liquidity levels rather than R multiples. Substituting a multiple would assume
away the thing being tested.
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
from research.ict_mss import detect_mss
from research.mtf_join import window_bounds

DATA = "historical/ES-5y/glbx-mdp3-20210724-20260723.ohlcv-1m.dbn.zst"
_SEEN = set()


def env(name, default):
    _SEEN.add(name)
    return os.environ.get(name, default)


START = env("MTF_START", "2021-07-25")
END = env("MTF_END", "2024-12-31")
CTX_TF = env("MTF_CTX", "15min")
EXEC_TF = env("MTF_EXEC", "1min")
MSS_MINUTES = int(env("MTF_MSS_MIN", "60"))      # window for the shift to print
RETEST_MINUTES = int(env("MTF_RETEST_MIN", "60"))
BUFFER = float(env("MTF_BUFFER", "0.5"))         # ATR beyond the context extreme
DISP_MULT = float(env("MTF_DISP", "1.0"))
# Which liquidity level counts as "the next *significant* draw". Taking the
# nearest level gives a median R:R of 0.27 — a target closer than the stop —
# which is the inverse of the 1:3 the methodology claims. The source says
# "significant", the 2022 model says "the opposite end of the swept range", and
# Silver Bullet says "typically 1:3", so nearest-level is not the rule. This is a
# specification ambiguity, so the whole curve is reported rather than a pick.
MIN_RR = float(env("MTF_MIN_RR", "0.0"))
OUT = env("MTF_OUT", "logs/exp27/mtf_sequence.json")
COST = 1.02

for k in os.environ:
    if k.startswith("MTF_") and k not in _SEEN:
        raise SystemExit(f"{k} was set but is not read by this script")

df = load_continuous_contract(DATA)
lo_t, hi_t = pd.Timestamp(START, tz="UTC"), pd.Timestamp(END, tz="UTC")


def slice_tf(tf):
    b = resample_ohlcv(df, tf) if tf != "1min" else df.copy()
    t = b["timestamp"]
    return b.loc[(t >= lo_t) & (t <= hi_t)].reset_index(drop=True)


ctx = slice_tf(CTX_TF)
ex = slice_tf(EXEC_TF)
ctx_o = smc_adapter.prepare_ohlc(ctx)
ex_o = smc_adapter.prepare_ohlc(ex)
c_high, c_low, c_close = (ctx[c].to_numpy() for c in ("high", "low", "close"))
e_high, e_low, e_close = (ex[c].to_numpy() for c in ("high", "low", "close"))
c_stamp, e_stamp = ctx["timestamp"], ex["timestamp"]
e_naive = e_stamp.dt.tz_localize(None).to_numpy()
c_atr = calc_atr(ctx).to_numpy()
day = c_stamp.dt.tz_convert("America/New_York").dt.date.to_numpy()
print(f"context {CTX_TF} {len(ctx):,} bars | execution {EXEC_TF} {len(ex):,} bars",
      flush=True)


def daily_bias():
    daily = resample_ohlcv(df, "1D", session_aligned=True)
    o = smc_adapter.prepare_ohlc(daily)
    _, sw = smc_adapter.detect_swings(o, "bias")
    stamps = daily["timestamp"].to_numpy()
    hs, ls, out, last = [], [], {}, "neutral"
    for s in sorted(sw, key=lambda x: x["candle_index"]):
        (hs if s["type"] == "swing_high" else ls).append(s["level"])
        if len(hs) >= 2 and len(ls) >= 2:
            up = hs[-1] > hs[-2] and ls[-1] > ls[-2]
            dn = hs[-1] < hs[-2] and ls[-1] < ls[-2]
            last = "bullish" if up else "bearish" if dn else "neutral"
        if s["candle_index"] < len(stamps):
            out[pd.Timestamp(stamps[s["candle_index"]])] = last
    return out


bias_at = daily_bias()
bkeys = np.array([k.value for k in sorted(bias_at)])
bvals = [bias_at[k] for k in sorted(bias_at)]
bpos = np.searchsorted(bkeys, c_stamp.astype("int64").to_numpy(), side="left") - 1
bias_ctx = np.array([bvals[p] if p >= 0 else "neutral" for p in bpos])

# Context leg: sweeps, and the liquidity levels that serve as targets.
c_shl, _ = smc_adapter.detect_swings(ctx_o, CTX_TF)
c_sw, c_lvl = c_shl["HighLow"].to_numpy(), c_shl["Level"].to_numpy()
liq_levels = sorted({z["level"] for z in smc_adapter.detect_liquidity(ctx_o, c_shl)})
liq_arr = np.array(liq_levels) if liq_levels else np.array([])
print(f"{len(liq_arr)} context liquidity levels", flush=True)

events = []
last_hi = last_lo = None
for i in range(len(ctx)):
    if not np.isnan(c_sw[i]):
        if c_sw[i] == 1:
            last_hi = c_lvl[i]
        elif c_sw[i] == -1:
            last_lo = c_lvl[i]
        continue
    agree_up = bias_ctx[i] == "bullish"
    agree_dn = bias_ctx[i] == "bearish"
    if last_hi is not None and c_high[i] > last_hi and agree_up:
        events.append((i, "up", c_low[i]))
    elif last_lo is not None and c_low[i] < last_lo and agree_dn:
        events.append((i, "down", c_high[i]))
print(f"{len(events)} context sweeps with bias agreeing", flush=True)

# Execution leg.
e_shl, e_swings = smc_adapter.detect_swings(ex_o, EXEC_TF)
e_disp = {d["candle_index"] for d in detect_displacements(ex, atr_mult=DISP_MULT)}
mss_all = detect_mss(ex, e_swings, e_disp)
mss_idx = np.array([m["index"] for m in mss_all])
mss_dir = np.array([m["direction"] for m in mss_all])
e_fvgs = {f["candle_index"]: f for f in smc_adapter.detect_fvgs(ex_o)}
print(f"{len(mss_all)} execution MSS, {len(e_fvgs)} execution FVGs", flush=True)

intrabar = Intrabar(df)
mclose = df.set_index("timestamp")["close"]
rng = np.random.default_rng(8)


def close_at(t):
    k = mclose.index.searchsorted(t, side="right") - 1
    return float(mclose.iloc[k]) if k >= 0 else None


def next_liquidity(price, sign, risk):
    """Nearest context liquidity level at least MIN_RR away, or None.

    "Nearest" alone selects minor levels a fraction of the stop distance away.
    MIN_RR expresses "significant" as a floor in R.
    """
    if len(liq_arr) == 0:
        return None
    floor = risk * MIN_RR
    ahead = (liq_arr[liq_arr >= price + floor] if sign > 0
             else liq_arr[liq_arr <= price - floor])
    if len(ahead) == 0:
        return None
    return float(ahead.min() if sign > 0 else ahead.max())


rows, stats = [], {"no_mss": 0, "no_fvg": 0, "no_retest": 0, "no_target": 0,
                   "bad_geometry": 0, "filled": 0}

for ci, d, invalidating in events:
    if np.isnan(c_atr[ci]) or c_atr[ci] <= 0:
        continue
    sign = 1.0 if d == "up" else -1.0
    want = "bullish" if d == "up" else "bearish"
    close_ts = c_stamp.iloc[ci]

    s, e = window_bounds(e_naive, close_ts.tz_localize(None), MSS_MINUTES)
    if s is None:
        continue
    hit = np.flatnonzero((mss_idx >= s) & (mss_idx < e) & (mss_dir == want))
    if len(hit) == 0:
        stats["no_mss"] += 1
        continue
    m = mss_all[int(hit[0])]

    f = e_fvgs.get(m["index"])
    if f is None:
        stats["no_fvg"] += 1
        continue

    rs, re_ = window_bounds(e_naive, pd.Timestamp(e_stamp.iloc[m["index"]]).tz_localize(None),
                            RETEST_MINUTES)
    if rs is None:
        continue
    top, bot = f["top"], f["bottom"]
    fill = None
    for k in range(rs, min(re_, len(ex))):
        if e_high[k] >= bot and e_low[k] <= top:
            fill = k
            break
    if fill is None:
        stats["no_retest"] += 1
        continue

    entry = e_close[fill]
    stop = invalidating - sign * BUFFER * c_atr[ci]
    risk = abs(entry - stop)
    if risk <= 0 or (sign > 0 and entry <= stop) or (sign < 0 and entry >= stop):
        stats["bad_geometry"] += 1
        continue
    target = next_liquidity(entry, sign, risk)
    if target is None or (sign > 0 and target <= entry) or (sign < 0 and target >= entry):
        stats["no_target"] += 1
        continue

    rr = abs(target - entry) / risk
    t0 = e_stamp.iloc[fill]
    res = intrabar.first_touch(t0, session_end(t0), "LONG" if sign > 0 else "SHORT",
                               stop, target)
    cost = COST / risk
    if res == "TP_HIT":
        r = rr - cost
    elif res == "SL_HIT":
        r = -1.0 - cost
    else:
        px = close_at(session_end(t0))
        if px is None:
            continue
        r = (px - entry) * sign / risk - cost
    stats["filled"] += 1
    rows.append({"r": r, "rr": rr, "risk": risk, "cost_r": cost, "day": day[ci],
                 "outcome": res or "TIME"})

print("\nfunnel: " + "  ".join(f"{k}={v}" for k, v in stats.items()))
if not rows:
    raise SystemExit("no completed sequences")

r = np.array([x["r"] for x in rows])
rr = np.array([x["rr"] for x in rows])
cr = np.array([x["cost_r"] for x in rows])
risk = np.array([x["risk"] for x in rows])
dd = np.array([x["day"] for x in rows])

uniq = np.unique(dd)
by = {k: r[dd == k] for k in uniq}
draws = np.empty(2000)
for k in range(2000):
    pick = rng.choice(uniq, size=len(uniq), replace=True)
    draws[k] = np.concatenate([by[x] for x in pick]).mean()
lo, hi = np.percentile(draws, [2.5, 97.5])

wins = sum(1 for x in rows if x["outcome"] == "TP_HIT")
losses = sum(1 for x in rows if x["outcome"] == "SL_HIT")
print(f"\nn={len(rows)}  fill rate {len(rows)/max(len(events),1)*100:.1f}% of "
      f"{len(events)} sweeps")
print(f"  median risk {np.median(risk):.2f} pt   median cost/R {np.median(cr):.3f}")
print(f"  median R:R  {np.median(rr):.2f}        mean R:R {rr.mean():.2f}")
print(f"  outcomes: TP {wins}  SL {losses}  time {len(rows)-wins-losses}")
print(f"  barrier win rate {wins/max(wins+losses,1)*100:.2f}%  "
      f"break-even needs {(1+np.median(cr))/(1+np.median(rr))*100:.2f}%")
print(f"  mean net R {r.mean():+.4f}  95% [{lo:+.4f}, {hi:+.4f}]"
      f"{'  ***' if lo > 0 else ''}")

Path(OUT).parent.mkdir(parents=True, exist_ok=True)
json.dump({"n": len(rows), "fill_pct": len(rows) / max(len(events), 1) * 100,
           "median_rr": float(np.median(rr)), "median_cost_r": float(np.median(cr)),
           "barrier_win_rate": wins / max(wins + losses, 1) * 100,
           "mean_r": float(r.mean()), "ci": [float(lo), float(hi)],
           "funnel": stats}, open(OUT, "w"), indent=2)
print(f"wrote {OUT}")
