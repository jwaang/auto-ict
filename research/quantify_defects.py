"""Size the two resolver disagreements found in experiment 26's trades.

A: entries stamped 16:00 ET. That is the force-close hour, so the engine opens a
   position and closes it on the next bar. A full round turn of costs for a
   fifteen-minute hold.

B: positions held past their own session. The engine closes on the first bar
   whose ET hour is 16, and on a holiday or half-day no such bar exists, so the
   position carries into later sessions.
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backtest.nullmodel import session_end

ET = "America/New_York"
blob = json.load(open("logs/exp27/exp26_trades.json"))
trades = [t for t in blob["trades"] if t.get("entry_time") and t.get("exit_time")]

at_cutoff, overnight = [], []
for t in trades:
    ts = pd.Timestamp(t["entry_time"])
    xt = pd.Timestamp(t["exit_time"])
    et = ts.tz_convert(ET)
    if et.hour == 16:
        at_cutoff.append(t)
    held = xt - ts
    if xt > session_end(ts):
        overnight.append({"entry": str(et), "exit": str(xt.tz_convert(ET)),
                          "held_h": round(held.total_seconds() / 3600, 1),
                          "reason": t.get("exit_reason"),
                          "pnl": t.get("pnl_dollars")})

print(f"total trades: {len(trades)}")

print(f"\nA. entries on the 16:00 ET bar: {len(at_cutoff)}")
if at_cutoff:
    holds = [(pd.Timestamp(t["exit_time"]) - pd.Timestamp(t["entry_time"])).total_seconds() / 60
             for t in at_cutoff]
    print(f"   median hold: {pd.Series(holds).median():.0f} min")
    print(f"   costs paid:  ${sum(t.get('costs') or 0 for t in at_cutoff):,.0f}")
    print(f"   net P&L:     ${sum(t.get('pnl_dollars') or 0 for t in at_cutoff):,.0f}")
    print(f"   exit reasons: {pd.Series([t.get('exit_reason') for t in at_cutoff]).value_counts().to_dict()}")

print(f"\nB. positions held past their session cutoff: {len(overnight)}")
if overnight:
    ov = pd.DataFrame(overnight)
    print(f"   median hold: {ov.held_h.median():.1f} h, max {ov.held_h.max():.1f} h")
    print(f"   net P&L:     ${ov.pnl.sum():,.0f}")
    print(f"   exit reasons: {ov.reason.value_counts().to_dict()}")
    print("\n   longest held:")
    for r in ov.nlargest(8, "held_h").to_dict("records"):
        print(f"     {r['entry']} -> {r['exit']}  {r['held_h']:>6.1f}h  "
              f"{r['reason']:<12} ${r['pnl']:>9,.0f}")
