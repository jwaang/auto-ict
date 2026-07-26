"""Silver Bullet: the one ICT claim with a specific number attached.

The claim is 55-65% at 1:3 risk-reward, which is roughly +1.4R per trade. It is
precisely falsifiable, and the repo's earlier test of it was not a test at all —
`backtest/strategies/common.py` records that confining the sequence to a one-hour
window produced zero trades over a full year at 15m and 5m, because the window
holds 4 and 12 bars against the ~15 a structure shift needs. That is arithmetic,
not evidence. A one-hour window holds 60 one-minute bars, so 1-minute execution is
the only version that can exist.

**The break-even is not 25%.** That is the claim's zero-cost figure. Silver Bullet
stops go beyond the creating candle's wick — an FVG candle on 1-minute, so 1-2
points of risk against a 1.02-point round turn, which is 0.5 to 1.0 R of cost. At
1:3 with 0.7R of cost a win returns +2.3R and a loss −1.7R, putting break-even
near 42%. The claimed 55-65% still clears that, so the test stays meaningful —
but the realised figure is what gets reported, not the naive one.

The 5-minute cell is run as a **control**. It should produce almost nothing. If it
does not, the window logic is wrong and the 1-minute result cannot be trusted.
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
from config import SILVER_BULLET_WINDOWS
from data.historical import load_continuous_contract, resample_ohlcv
from ict import smc_adapter
from ict.displacement import detect_displacements
from research.ict_mss import detect_mss
from research.sb_windows import window_for

DATA = "historical/ES-5y/glbx-mdp3-20210724-20260723.ohlcv-1m.dbn.zst"
_SEEN = set()


def env(name, default):
    _SEEN.add(name)
    return os.environ.get(name, default)


START = env("SB_START", "2021-07-25")
END = env("SB_END", "2024-12-31")
EXEC_TF = env("SB_EXEC", "1min")
MIN_RR = float(env("SB_MIN_RR", "2.0"))     # "next *significant* draw"
# The claim is 55-65% **at 1:3**. Measuring at whatever R:R the liquidity target
# happens to give (6.80 realised) does not test it: a 13% win rate at 1:6.8 is
# what fair barriers predict and says nothing about the stated geometry. Set
# SB_FIXED_RR=3 to test the claim at its own terms.
FIXED_RR = float(env("SB_FIXED_RR", "0"))
BUFFER_TICKS = float(env("SB_BUFFER", "1.0"))   # beyond the creating candle wick
OUT = env("SB_OUT", "logs/exp27/silver_bullet.json")
COST = 1.02
TICK = 0.25

for k in os.environ:
    if k.startswith("SB_") and k not in _SEEN:
        raise SystemExit(f"{k} was set but is not read by this script")

df = load_continuous_contract(DATA)
lo_t, hi_t = pd.Timestamp(START, tz="UTC"), pd.Timestamp(END, tz="UTC")


def slice_tf(tf):
    b = resample_ohlcv(df, tf) if tf != "1min" else df.copy()
    t = b["timestamp"]
    return b.loc[(t >= lo_t) & (t <= hi_t)].reset_index(drop=True)


ctx = slice_tf("15min")
ex = slice_tf(EXEC_TF)
ctx_o = smc_adapter.prepare_ohlc(ctx)
ex_o = smc_adapter.prepare_ohlc(ex)
e_high, e_low, e_close = (ex[c].to_numpy() for c in ("high", "low", "close"))
e_stamp = ex["timestamp"]
n = len(ex)
print(f"context 15m {len(ctx):,} bars | execution {EXEC_TF} {n:,} bars", flush=True)

# Context liquidity, kept with its timestamp so targets can be restricted to
# levels that existed *before* the window opened — the source marks liquidity
# pre-window, and using a level formed inside the window would be look-ahead.
c_shl, _ = smc_adapter.detect_swings(ctx_o, "15min")
liq = [(pd.Timestamp(ctx["timestamp"].iloc[z["candle_index"]]), z["level"])
       for z in smc_adapter.detect_liquidity(ctx_o, c_shl)
       if z.get("candle_index") is not None and z["candle_index"] < len(ctx)]
liq.sort()
liq_ts = np.array([t.value for t, _ in liq])
liq_lv = np.array([lv for _, lv in liq])
print(f"{len(liq)} context liquidity levels", flush=True)

_, e_swings = smc_adapter.detect_swings(ex_o, EXEC_TF)
e_disp = {d["candle_index"] for d in detect_displacements(ex, atr_mult=1.0)}
mss_all = detect_mss(ex, e_swings, e_disp)
e_fvgs = {f["candle_index"]: f for f in smc_adapter.detect_fvgs(ex_o)}
print(f"{len(mss_all)} execution MSS, {len(e_fvgs)} execution FVGs", flush=True)

# Which execution bars sit inside a Silver Bullet window, and which window.
win = np.array([window_for(t) if t is not None else None for t in e_stamp])
in_win = np.array([w is not None for w in win])
print(f"{in_win.sum():,} execution bars inside a window "
      f"({in_win.mean()*100:.1f}% of the session)", flush=True)

intrabar = Intrabar(df)
mclose = df.set_index("timestamp")["close"]
rng = np.random.default_rng(31)


def close_at(t):
    k = mclose.index.searchsorted(t, side="right") - 1
    return float(mclose.iloc[k]) if k >= 0 else None


def pre_window_liquidity(price, sign, risk, window_start):
    """Nearest level at least MIN_RR away that existed before the window opened."""
    mask = liq_ts < pd.Timestamp(window_start).value
    if not mask.any():
        return None
    avail = liq_lv[mask]
    floor = risk * MIN_RR
    ahead = avail[avail >= price + floor] if sign > 0 else avail[avail <= price - floor]
    if len(ahead) == 0:
        return None
    return float(ahead.min() if sign > 0 else ahead.max())


rows, funnel = [], {"mss_in_window": 0, "no_fvg": 0, "no_retest_in_window": 0,
                    "no_target": 0, "bad_geometry": 0, "filled": 0}

for m in mss_all:
    i = m["index"]
    if not in_win[i]:
        continue
    funnel["mss_in_window"] += 1
    f = e_fvgs.get(i)
    if f is None:
        funnel["no_fvg"] += 1
        continue

    # The retrace must also complete inside the same window.
    this_win = win[i]
    top, bot = f["top"], f["bottom"]
    fill = None
    for k in range(i + 1, min(i + 61, n)):
        if win[k] != this_win:
            break
        if e_high[k] >= bot and e_low[k] <= top:
            fill = k
            break
    if fill is None:
        funnel["no_retest_in_window"] += 1
        continue

    sign = 1.0 if m["direction"] == "bullish" else -1.0
    entry = e_close[fill]
    # Stop beyond the wick of the candle that created the gap.
    wick = e_low[i] if sign > 0 else e_high[i]
    stop = wick - sign * BUFFER_TICKS * TICK
    risk = abs(entry - stop)
    if risk <= 0 or (sign > 0 and entry <= stop) or (sign < 0 and entry >= stop):
        funnel["bad_geometry"] += 1
        continue

    day = pd.Timestamp(e_stamp.iloc[i]).tz_convert("America/New_York").normalize()
    w_start = day + pd.Timedelta(hours=SILVER_BULLET_WINDOWS[this_win][0])
    if FIXED_RR > 0:
        target = entry + sign * risk * FIXED_RR
    else:
        target = pre_window_liquidity(entry, sign, risk, w_start)
        if target is None:
            funnel["no_target"] += 1
            continue

    rr = abs(target - entry) / risk
    t0 = e_stamp.iloc[fill]
    res = intrabar.first_touch(t0, session_end(t0),
                               "LONG" if sign > 0 else "SHORT", stop, target)
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
    funnel["filled"] += 1
    rows.append({"r": r, "rr": rr, "risk": risk, "cost_r": cost,
                 "outcome": res or "TIME",
                 "day": pd.Timestamp(t0).tz_convert("America/New_York").date(),
                 "window": this_win})

print("\nfunnel: " + "  ".join(f"{k}={v}" for k, v in funnel.items()))
if not rows:
    print("\nNo setups. On 5-minute this is the expected control result: the "
          "window holds 12 bars against the ~15 a structure shift needs.")
    Path(OUT).parent.mkdir(parents=True, exist_ok=True)
    json.dump({"exec_tf": EXEC_TF, "n": 0, "funnel": funnel}, open(OUT, "w"), indent=2)
    raise SystemExit(0)

r = np.array([x["r"] for x in rows])
rr = np.array([x["rr"] for x in rows])
cr = np.array([x["cost_r"] for x in rows])
dd = np.array([x["day"] for x in rows])
wins = sum(1 for x in rows if x["outcome"] == "TP_HIT")
losses = sum(1 for x in rows if x["outcome"] == "SL_HIT")

uniq = np.unique(dd)
by = {k: r[dd == k] for k in uniq}
draws = np.empty(2000)
for k in range(2000):
    pick = rng.choice(uniq, size=len(uniq), replace=True)
    draws[k] = np.concatenate([by[x] for x in pick]).mean()
lo, hi = np.percentile(draws, [2.5, 97.5])

med_rr, med_cr = float(np.median(rr)), float(np.median(cr))
breakeven = (1 + med_cr) / (1 + med_rr) * 100
winrate = wins / max(wins + losses, 1) * 100

print(f"\nn={len(rows)}   median risk {np.median([x['risk'] for x in rows]):.2f} pt")
print(f"  median R:R {med_rr:.2f}   median cost/R {med_cr:.3f}")
print(f"  outcomes: TP {wins}  SL {losses}  time {len(rows)-wins-losses}")
print(f"  barrier win rate {winrate:.2f}%")
print(f"  break-even at realised geometry {breakeven:.2f}%  "
      f"(the claim's own zero-cost figure would be {100/(1+med_rr):.2f}%)")
print(f"  claim is 55-65% -> {'CLEARS' if winrate > breakeven else 'FAILS'} its own bar")
print(f"  mean net R {r.mean():+.4f}  95% [{lo:+.4f}, {hi:+.4f}]"
      f"{'  ***' if lo > 0 else ''}")
by_win = {}
for x in rows:
    by_win.setdefault(x["window"], []).append(x["r"])
print("  by window: " + "  ".join(f"{k} n={len(v)} meanR={np.mean(v):+.3f}"
                                  for k, v in sorted(by_win.items())))

Path(OUT).parent.mkdir(parents=True, exist_ok=True)
json.dump({"exec_tf": EXEC_TF, "n": len(rows), "funnel": funnel,
           "median_rr": med_rr, "median_cost_r": med_cr,
           "win_rate": winrate, "breakeven": breakeven,
           "mean_r": float(r.mean()), "ci": [float(lo), float(hi)]},
          open(OUT, "w"), indent=2, default=str)
print(f"wrote {OUT}")
