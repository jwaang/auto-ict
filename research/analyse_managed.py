"""Paired exit-rule comparison: managed exits against the same entries unmanaged.

Managed exits change the payoff functional, so barrier win rate, `_geometry` and
every paired random-direction null in this repo stop applying — there is no
single stop/target pair left to score. The clean question is instead:

    does managed_exit(entry_i, direction_i, path_i) beat
       unmanaged_exit(entry_i, direction_i, path_i)?

so the statistic is the per-trade paired delta in net R, with a bootstrap
interval. A paired t is reported too, but the bootstrap is the one to trust:
exit-rule deltas are lumpy — many trades unchanged, a few winners clipped, a few
losers rescued at breakeven.

Trade management also changes how long a position occupies one of the three
concurrency slots, so the two runs do not necessarily take the same entries.
Experiment 29 showed that displacement effect is real and large. Pairing is
therefore on the intersection, and the unpaired remainder is reported rather
than quietly dropped.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

UNMANAGED = "logs/exp27/exp26_trades.json"
MANAGED = "logs/exp27/exp31_managed.json"
POINT_VALUE = 50.0


def load(path):
    """Key each trade by entry bar and direction, with its net result in R."""
    out = {}
    for t in json.load(open(path))["trades"]:
        if not t.get("entry_time") or t.get("status") != "CLOSED":
            continue
        risk = abs(float(t["entry_price"]) - float(t["stop_loss"]))
        qty = t.get("quantity") or t.get("size") or 0
        if risk <= 0 or not qty:
            continue
        # Net R for the whole position, so a half-size partial counts as half.
        r = (t.get("pnl_dollars") or 0) / (risk * POINT_VALUE * qty)
        out[(str(pd.Timestamp(t["entry_time"])), t["direction"])] = {
            "r": r, "net": t.get("pnl_dollars") or 0,
            "reason": t.get("exit_reason"), "trade": t,
        }
    return out


un, mg = load(UNMANAGED), load(MANAGED)
shared = sorted(set(un) & set(mg))
d = np.array([mg[k]["r"] - un[k]["r"] for k in shared])

print(f"unmanaged trades {len(un)}   managed trades {len(mg)}")
print(f"paired on identical entry bar and direction: {len(shared)}")
print(f"  only unmanaged: {len(set(un) - set(mg))}   only managed: {len(set(mg) - set(un))}")

if len(d):
    rng = np.random.default_rng(0)
    boot = np.array([rng.choice(d, size=len(d), replace=True).mean() for _ in range(10000)])
    lo, hi = np.percentile(boot, [2.5, 97.5])
    t = d.mean() / (d.std(ddof=1) / np.sqrt(len(d))) if d.std(ddof=1) > 0 else float("nan")
    print(f"\nmean delta   {d.mean():+.4f} R   95% bootstrap [{lo:+.4f}, {hi:+.4f}]")
    print(f"median delta {np.median(d):+.4f} R   paired t {t:+.2f}")
    print(f"improved {100 * (d > 1e-9).mean():.1f}%   worsened {100 * (d < -1e-9).mean():.1f}%   "
          f"unchanged {100 * (np.abs(d) <= 1e-9).mean():.1f}%")
    print(f"\nregistered before the run: mean delta > +0.03 R with the interval "
          f"clear of zero would be a real result.")
    verdict = ("SURPRISE — investigate" if d.mean() > 0.03 and lo > 0
               else "noise" if abs(d.mean()) <= 0.01
               else "worse, as predicted" if d.mean() < 0 else "positive but under the bar")
    print(f"verdict: {verdict}")

for tag, book in (("unmanaged", un), ("managed", mg)):
    reasons = pd.Series([v["reason"] for v in book.values()]).value_counts().to_dict()
    print(f"\n{tag:10} net ${sum(v['net'] for v in book.values()):>11,.0f}   "
          f"mean R {np.mean([v['r'] for v in book.values()]):+.4f}   {reasons}")
