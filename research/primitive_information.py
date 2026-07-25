"""Does any ICT primitive carry directional information at all?

Seventy-three configurations tested how to *combine* primitives into a trade.
None tested whether any primitive predicts anything. That is backwards: it tunes
an ensemble without checking whether the base learners beat chance.

The measurement problem those configurations hit was sample size. A strategy
yields a few hundred trades a year, so three standard errors is +5 to +17
win-rate points while the economic bar is +4 — the instrument was blunter than
the effect. Here one *detection* is one sample rather than one trade, so n runs
to tens of thousands and 3 SE falls under a point.

No trade simulation, no costs, no position cap, no concurrency. Only: when a
detector fires with an implied direction, does price go that way?

Two benchmarks, because they answer different questions:

  coin flip   — a random direction is right 50% of the time at any bar,
                whatever the drift. Beating this is directional information.
  always long — ES rose over the sample, so a primitive that mostly says
                "bullish" beats the coin flip on drift alone. This is the trap
                premium/discount already fell into, voting bearish 97% of the
                time and reading as a signal.

A primitive only counts if it beats the coin flip *and* is not explained by its
own long/short split.
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

DATA = "historical/ES-5y/glbx-mdp3-20210724-20260723.ohlcv-1m.dbn.zst"
START = os.environ.get("PRIM_START", "2021-07-25")
END = os.environ.get("PRIM_END", "2024-12-31")
TFS = os.environ.get("PRIM_TFS", "1min,5min,15min").split(",")
HORIZONS = [1, 4, 12, 24]
OUT = os.environ.get("PRIM_OUT", "logs/exp27/primitives.json")


def detections(ohlc: pd.DataFrame, tf: str) -> dict:
    """Every primitive that carries an implied direction, as (index, dir) pairs.

    Only causal fields are read. `filled` and `mitigated_index` describe what
    happened *after* the detection bar and are ignored.
    """
    shl = smc_adapter.detect_swings(ohlc, tf)[0]
    out = {}

    fvgs = smc_adapter.detect_fvgs(ohlc)
    out["FVG"] = [(f["candle_index"], f["type"]) for f in fvgs]

    obs = smc_adapter.detect_order_blocks(ohlc, shl)
    out["OrderBlock"] = [(o["candle_index"], o["type"]) for o in obs
                         if o.get("candle_index") is not None]

    breaks, _ = smc_adapter.detect_bos_choch(ohlc, shl)
    for name in ("BOS", "CHoCH"):
        rows = [b for b in breaks if b.get("type", "").upper().startswith(name.upper())]
        out[name] = [(b["candle_index"],
                      "bullish" if b.get("direction", 1) == 1 or
                      str(b.get("direction", "")).lower() in ("bullish", "up")
                      else "bearish")
                     for b in rows if b.get("candle_index") is not None]

    disp = detect_displacements(ohlc)
    out["Displacement"] = [(d["candle_index"], d["direction"]) for d in disp
                           if d.get("candle_index") is not None
                           and d.get("direction") in ("bullish", "bearish")]

    return out


def score(idx_dirs, closes, n_bars, days):
    """Hit rate at each horizon, with a day-block bootstrap for the interval.

    Detections are not independent. They cluster in time — several fire in the
    same session — and at horizon h consecutive detections share h bars of
    forward return, so the naive sqrt(0.25/n) standard error is far too small
    and inflates z exactly where a spurious positive would appear.

    The interval is therefore a block bootstrap that resamples whole trading
    days, which keeps both the intraday clustering and the overlap inside a
    block. `z_naive` is kept alongside only to show how large the difference is.
    """
    rows = {}
    idx = np.array([i for i, _ in idx_dirs], dtype=int)
    bull = np.array([d == "bullish" for _, d in idx_dirs])
    if len(idx) == 0:
        return rows
    rng = np.random.default_rng(7)
    for h in HORIZONS:
        ok = idx + h < n_bars
        if ok.sum() < 30:
            continue
        i, b = idx[ok], bull[ok]
        fwd = closes[i + h] - closes[i]
        hit = np.where(b, fwd > 0, fwd < 0)
        n = len(hit)
        wr = hit.mean() * 100
        se_naive = np.sqrt(0.25 / n) * 100

        # Block bootstrap over trading days.
        day = days[i]
        uniq = np.unique(day)
        by_day = {d: hit[day == d] for d in uniq}
        draws = np.empty(2000)
        for k in range(2000):
            pick = rng.choice(uniq, size=len(uniq), replace=True)
            draws[k] = np.concatenate([by_day[d] for d in pick]).mean() * 100
        se_block = float(draws.std(ddof=1))
        lo, hi = np.percentile(draws, [2.5, 97.5])

        rows[h] = {
            "n": int(n),
            "n_days": int(len(uniq)),
            "win_rate": round(float(wr), 2),
            "edge_vs_coinflip": round(float(wr - 50), 2),
            "z_naive": round(float((wr - 50) / se_naive), 2),
            "z_block": round(float((wr - 50) / se_block), 2) if se_block > 0 else None,
            "ci95": [round(float(lo - 50), 2), round(float(hi - 50), 2)],
            "pct_bullish": round(float(b.mean() * 100), 1),
            "always_long_wr": round(float((fwd > 0).mean() * 100), 2),
        }
    return rows


df = load_continuous_contract(DATA)
results = {}

for tf in TFS:
    bars = resample_ohlcv(df, tf) if tf != "1min" else df.copy()
    ts = bars["timestamp"]
    m = (ts >= pd.Timestamp(START, tz="UTC")) & (ts <= pd.Timestamp(END, tz="UTC"))
    bars = bars.loc[m].reset_index(drop=True)
    ohlc = smc_adapter.prepare_ohlc(bars)
    closes = bars["close"].to_numpy()
    days = bars["timestamp"].dt.tz_convert("America/New_York").dt.date.to_numpy()
    print(f"\n### {tf}: {len(bars):,} bars {START}..{END}", flush=True)

    for name, dets in detections(ohlc, tf).items():
        rows = score(dets, closes, len(bars), days)
        if not rows:
            print(f"  {name:14} {len(dets):>7} detections — too few resolvable")
            continue
        results[f"{tf}:{name}"] = rows
        for h, r in rows.items():
            zb = r["z_block"]
            flag = "***" if zb is not None and abs(zb) > 3 and r["n"] >= 5000 else "   "
            print(f"  {name:14} h={h:<3} n={r['n']:>7} ({r['n_days']:>4}d) "
                  f"wr {r['win_rate']:>6.2f} edge {r['edge_vs_coinflip']:>+6.2f} "
                  f"z_blk {str(zb):>7} (naive {r['z_naive']:>+6.2f}) "
                  f"ci [{r['ci95'][0]:>+6.2f},{r['ci95'][1]:>+6.2f}] "
                  f"bull% {r['pct_bullish']:>5.1f} longWR {r['always_long_wr']:>5.2f} {flag}",
                  flush=True)

Path(OUT).parent.mkdir(parents=True, exist_ok=True)
json.dump(results, open(OUT, "w"), indent=2)
print(f"\nwrote {OUT}")
