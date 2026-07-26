"""Order block, breaker and mitigation block: three verdicts from one population.

All three are the same zone read three ways, which is why one correct detector
unblocks them:

  order block       first retest, expect continuation in the OB's direction
  breaker           the OB was violated by a **body close** and structure shifted
                    the other way; the zone flips polarity and is retested in the
                    **new** direction — "same level, opposite trade"
  mitigation block  a *later* retest of an OB that was never violated, which is
                    the source's claim that blocks weaken with each retest

The control throughout is a geometry-matched zone price also returned to — same
width, same signed offset, anchored at a random other bar. A control price never
reached measures "does price come back", not "does this zone work".

Registered before running: order blocks number 226 at 15m and 463 at 5m, far
short of the 5,000 floor, and breakers are a subset of those. **Every result here
is recorded as unknown regardless of its point estimate**, headlined by its
sample count rather than its effect. That guard exists because two prior
headlines were retracted for exactly this shape.
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
from research.ict_mss import detect_mss
from research.ict_order_block import detect_order_blocks

DATA = "historical/ES-5y/glbx-mdp3-20210724-20260723.ohlcv-1m.dbn.zst"
_SEEN = set()


def env(name, default):
    _SEEN.add(name)
    return os.environ.get(name, default)


START = env("OBF_START", "2021-07-25")
END = env("OBF_END", "2024-12-31")
TF = env("OBF_TF", "5min")
WAIT = int(env("OBF_WAIT", "96"))          # bars allowed for a retest
HORIZONS = [1, 4, 12]
OUT = env("OBF_OUT", "logs/exp27/ob_family.json")

for k in os.environ:
    if k.startswith("OBF_") and k not in _SEEN:
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
rng = np.random.default_rng(12)

_, swings = smc_adapter.detect_swings(ohlc, TF)
disp = {d["candle_index"] for d in detect_displacements(bars, atr_mult=1.0)}
mss_list = detect_mss(bars, swings, disp)
mss_by_idx = {m["index"]: m["direction"] for m in mss_list}
fvgs = smc_adapter.detect_fvgs(ohlc)
blocks, funnel = detect_order_blocks(bars, fvgs, mss_list)
print(f"{TF}: {n:,} bars, {len(blocks)} order blocks")
print("funnel: " + "  ".join(f"{k}={v}" for k, v in funnel.items()), flush=True)


def touches(i, top, bot, limit, start_offset=1):
    """Indices where price re-enters the zone, in order."""
    hits = []
    for k in range(i + start_offset, min(i + start_offset + limit, n)):
        if high[k] >= bot and low[k] <= top:
            hits.append(k)
    return hits


def violated_with_shift(b):
    """Bar at which the block becomes a *breaker*, or None.

    Both are required: a body close beyond the far side, and an MSS in the
    opposite direction. A wick through is not a violation.

    Returns the **confirming MSS index**, not the violation index. The breaker
    does not exist until structure has shifted, so retests may only be counted
    after that bar. Returning the violation index instead counted reactions in
    the gap between the break and its confirmation — the same look-ahead already
    fixed on the order block itself, and it was inflating this arm by 14 to 23
    points while the others collapsed.
    """
    i = b["candle_index"]
    bull = b["type"] == "bullish"
    far = b["low"] if bull else b["high"]
    want = "bearish" if bull else "bullish"
    for k in range(i + 2, min(i + 2 + WAIT, n)):
        broke = close[k] < far if bull else close[k] > far
        if broke:
            for j in range(k, min(k + 12, n)):
                if mss_by_idx.get(j) == want:
                    return j
            return None
    return None


def score(samples, label):
    """Continuation rate against a matched control, per horizon."""
    if len(samples) < 30:
        print(f"  {label:22} n={len(samples):>5}  too few to report")
        return
    line = f"  {label:22} n={len(samples):>5}"
    for h in HORIZONS:
        real, ctrl, dr, dc = [], [], [], []
        for entry_idx, sign, top, bot in samples:
            if entry_idx + h >= n:
                continue
            fwd = close[entry_idx + h] - close[entry_idx]
            if fwd != 0:
                real.append(float(fwd * sign > 0))
                dr.append(day[entry_idx])
            # Control: same width, same offset, different time, also returned to.
            w = top - bot
            j = int(rng.integers(0, max(n - WAIT - h - 1, 1)))
            mid = close[j] + ((top + bot) / 2 - close[entry_idx])
            ch = touches(j, mid + w / 2, mid - w / 2, WAIT)
            if ch and ch[0] + h < n:
                f2 = close[ch[0] + h] - close[ch[0]]
                if f2 != 0:
                    ctrl.append(float(f2 * sign > 0))
                    dc.append(day[ch[0]])
        if len(real) < 30 or len(ctrl) < 30:
            continue
        rm, cm = np.mean(real) * 100, np.mean(ctrl) * 100
        line += f"   h{h}: {rm:5.1f}% vs {cm:5.1f}% = {rm - cm:+5.1f}"
        results[f"{label}_h{h}"] = {"n": len(real), "real": rm, "ctrl": cm,
                                    "diff": rm - cm}
    print(line, flush=True)


results = {}
ob_first, ob_later, breakers = [], [], []
for b in blocks:
    i, bull = b["candle_index"], b["type"] == "bullish"
    top, bot = b["high"], b["low"]
    sign = 1.0 if bull else -1.0
    # Retests may only begin after the block is knowable — that is, after its
    # confirming structure shift. Starting at i+2 counted reactions that
    # preceded the confirmation, which is look-ahead and inflated every effect.
    confirm = b["confirmed_index"]
    hits = [k for k in touches(i, top, bot, WAIT + confirm - i, start_offset=1)
            if k > confirm]
    v = violated_with_shift(b)
    if v is None:
        if hits:
            ob_first.append((hits[0], sign, top, bot))
        if len(hits) > 1:
            ob_later.append((hits[1], sign, top, bot))
    else:
        # Flipped polarity, retested after the violation.
        after = [k for k in touches(v, top, bot, WAIT, start_offset=1) if k > confirm]
        if after:
            breakers.append((after[0], -sign, top, bot))

print(f"\norder blocks {len(blocks)} -> first retest {len(ob_first)}, "
      f"later retest {len(ob_later)}, breakers {len(breakers)}\n")
score(ob_first, "order block 1st")
score(ob_later, "mitigation (2nd+)")
score(breakers, "breaker (flipped)")

Path(OUT).parent.mkdir(parents=True, exist_ok=True)
json.dump({"tf": TF, "n_blocks": len(blocks), "funnel": funnel,
           "n_first": len(ob_first), "n_later": len(ob_later),
           "n_breakers": len(breakers), "results": results},
          open(OUT, "w"), indent=2, default=float)
print(f"\nAll three are recorded as UNKNOWN regardless of point estimate — the "
      f"sample counts above are the headline, not the effects.")
print(f"wrote {OUT}")
