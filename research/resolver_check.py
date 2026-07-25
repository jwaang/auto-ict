"""Does Intrabar.first_touch agree with the engine on the engine's own trades?

The null model resolves its random entries with first_touch, while the strategy
win rate it is compared against comes from the engine. If the two resolvers
disagree, the edge is a difference of rulers rather than a difference of skill.
Same trades, same stops, same targets — the outcomes should match.
"""
import json
import sys
from pathlib import Path
from collections import Counter

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest.intrabar import Intrabar
from backtest.nullmodel import session_end
from data.historical import load_continuous_contract

blob = json.load(open("logs/exp27/exp26_trades.json"))
df = load_continuous_contract(
    "historical/ES-5y/glbx-mdp3-20210724-20260723.ohlcv-1m.dbn.zst")
intrabar = Intrabar(df)

pairs = Counter()
disagree = []
for t in blob["trades"]:
    if t.get("status") != "CLOSED" or not t.get("entry_time"):
        continue
    ts = pd.Timestamp(t["entry_time"])
    mine = intrabar.first_touch(ts, session_end(ts), t["direction"],
                                float(t["stop_loss"]), float(t["take_profit"]))
    engine = t.get("exit_reason")
    pairs[(engine, mine)] += 1
    if (engine == "TP_HIT") != (mine == "TP_HIT"):
        disagree.append({
            "entry_time": str(ts),
            "dir": t["direction"],
            "entry": t["entry_price"],
            "sl": t["stop_loss"],
            "tp": t["take_profit"],
            "exit_time": str(t.get("exit_time")),
            "exit_price": t.get("exit_price"),
            "engine": engine,
            "mine": mine,
        })

print("engine -> first_touch")
for (e, m), c in sorted(pairs.items(), key=lambda kv: -kv[1]):
    print(f"  {str(e):>12} -> {str(m):>12} : {c}")

print(f"\n{len(disagree)} trades where TP status differs")
for d in disagree[:12]:
    print(json.dumps(d, default=str))
json.dump(disagree, open("logs/exp27/disagree.json", "w"),
          indent=2, default=str)
