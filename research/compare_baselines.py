"""Judge the session-cutoff fix against predictions made before it ran.

Reads the pre-fix baseline and the post-fix re-baseline and checks each
pre-registered claim mechanically, so the verdict does not depend on reading a
table sympathetically. Red flags are checked too: a fix to a rule that was
handing out free profit should make results worse, and an improvement is a
reason to look harder rather than to celebrate.
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.historical import session_day

ET = "America/New_York"
PRE = "logs/exp27/exp26_trades_prefix.json"
POST = "logs/exp27/exp26_trades.json"


def load(path):
    blob = json.load(open(path))
    rows = []
    for t in blob["trades"]:
        if not t.get("entry_time"):
            continue
        ts = pd.Timestamp(t["entry_time"])
        xt = pd.Timestamp(t["exit_time"]) if t.get("exit_time") else None
        rows.append({
            "entry": ts, "exit": xt,
            "entry_et": ts.tz_convert(ET),
            "hold_h": (xt - ts).total_seconds() / 3600 if xt is not None else None,
            "reason": t.get("exit_reason"),
            "gross": t.get("gross_pnl") or 0,
            "net": t.get("pnl_dollars") or 0,
            "costs": t.get("costs") or 0,
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["sday_in"] = session_day(df.entry)
        df["sday_out"] = session_day(df.exit.fillna(df.entry))
    return blob["stats"], df


def summarise(tag, stats, df):
    print(f"\n--- {tag} ---")
    print(f"  trades            {len(df)}")
    print(f"  gross             ${df.gross.sum():>12,.2f}")
    print(f"  costs             ${df.costs.sum():>12,.2f}")
    print(f"  net               ${df.net.sum():>12,.2f}")
    print(f"  entries in 16:00h {(df.entry_et.dt.hour == 16).sum()}")
    print(f"  cross-session     {(df.sday_in != df.sday_out).sum()}")
    print(f"  longest hold      {df.hold_h.max():.1f} h")
    print(f"  exit reasons      {df.reason.value_counts().to_dict()}")
    se = df[df.reason == 'SESSION_END']
    print(f"  session-end gross ${se.gross.sum():>12,.2f} over {len(se)}")
    print(f"  exits at 17:00 ET {(df.exit.dropna().dt.tz_convert(ET).dt.hour == 17).sum()}")


def check(label, ok, detail):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: {detail}")
    return ok


pre_stats, pre = load(PRE)
post_stats, post = load(POST)
summarise("before the fix", pre_stats, pre)
summarise("after the fix", post_stats, post)

print("\n=== predictions registered before the run ===")
results = [
    check("gross falls toward break-even",
          post.gross.sum() < pre.gross.sum(),
          f"${pre.gross.sum():,.0f} -> ${post.gross.sum():,.0f}"),
    check("trade count drops by roughly 31",
          15 <= len(pre) - len(post) <= 60,
          f"{len(pre)} -> {len(post)} (delta {len(pre) - len(post)})"),
    check("no entry in the 16:00 ET hour",
          (post.entry_et.dt.hour == 16).sum() == 0,
          f"{(post.entry_et.dt.hour == 16).sum()} remain"),
    check("no trade spans a session day",
          (post.sday_in != post.sday_out).sum() == 0,
          f"{(post.sday_in != post.sday_out).sum()} remain "
          f"(was {(pre.sday_in != pre.sday_out).sum()})"),
    check("longest hold is intraday",
          post.hold_h.max() < 24,
          f"{pre.hold_h.max():.1f} h -> {post.hold_h.max():.1f} h"),
]

print("\n=== red flags (a PASS here means the flag is NOT raised) ===")
flags = [
    check("session-end gross did not rise",
          post[post.reason == 'SESSION_END'].gross.sum()
          <= pre[pre.reason == 'SESSION_END'].gross.sum(),
          f"${pre[pre.reason == 'SESSION_END'].gross.sum():,.0f} -> "
          f"${post[post.reason == 'SESSION_END'].gross.sum():,.0f}"),
    check("no exits at 17:00 ET",
          (post.exit.dropna().dt.tz_convert(ET).dt.hour == 17).sum() == 0,
          f"{(post.exit.dropna().dt.tz_convert(ET).dt.hour == 17).sum()} found"),
    check("net did not improve materially",
          post.net.sum() <= pre.net.sum() + 5000,
          f"${pre.net.sum():,.0f} -> ${post.net.sum():,.0f}"),
]

print(f"\npredictions {sum(results)}/{len(results)}   red flags clear {sum(flags)}/{len(flags)}")
