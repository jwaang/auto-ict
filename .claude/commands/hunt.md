---
description: One edge-hunting iteration on the ICT backtester — orient, pick one hypothesis, consult Codex, run, log
---

# /hunt — one research iteration

Run **one** hypothesis. Finish with a logged result either way: an edge measured, or a
hypothesis killed with numbers. Never end an iteration with an unlogged run.

Data: `historical/ES-5y/glbx-mdp3-20210724-20260723.ohlcv-1m.dbn.zst`

`historical/` and `.venv/` are gitignored, so a fresh worktree has neither, and `py` is
an interactive alias that a tool shell does not see. Run this once per worktree, then
use `.venv/bin/python` in place of `py`:

```bash
[ -e historical ] || ln -s "$(git rev-parse --git-common-dir)/../historical" historical
[ -e .venv ]      || ln -s "$(git rev-parse --git-common-dir)/../.venv" .venv
```

## 1. Orient (read only, no edits)

```bash
sed -n '1,120p' docs/BACKTEST-RESULTS-LOG.md      # newest experiment is at the top
python3 -c "import json;print(sorted(json.loads(l)['label'] for l in open('logs/experiments.jsonl')))"
git log --oneline -8
```

Read the "Where this left off" paragraph in CLAUDE.md. **A hypothesis already in the
label list or the results log is spent — pick a different one.**

## 2. Pick ONE hypothesis

It must name a mechanism ("X subtracts edge because Y"), not nudge a parameter. It must
be falsifiable by one sweep. Backlog, best first — strike through as spent:

~~1. The same trades at a 30-point stop.~~ **Spent — experiment 27.** Edge flat at
   every width, max |z| 0.74, mean net R negative throughout.

~~2. The +1.2 direction component.~~ **Spent — experiment 28.** It was an artifact of
   two faults in the day-trade cutoff. On the fixed baseline it is −0.9 at z −0.53.
   Items that assumed a positive component to build on are dead with it.

1. **Market entry on the signal bar.** Keep the bias, drop the retracement wait.
   Experiment 26 measured timing at −2.0 points; this tests whether that penalty goes
   neutral. One cell, ~22 min. Note it now has no positive direction component to add
   back, so a neutral result still leaves nothing.
2. **Bias alone, no ICT trigger.** Every kill-zone bar with a directional bias, fixed
   geometry, no FVG/OB requirement. The paired null scores direction *at the strategy's
   own bars*, so removing the trigger changes the population — it answers a
   neighbouring question, is the bias predictive at all, at n in the thousands where z
   can clear 3.
3. **A different instrument or horizon.** Same code, new data. Costs its own download.
   After experiment 28 this is the honest front-runner: nothing positive has been
   measured on 15-minute ES.
4. **A different data source.** Order flow or similar. Outside what this repo can
   currently load, so it is a decision rather than an experiment.

Out of backlog → one research pass, 10 minutes, WebSearch/WebFetch (Exa MCP if it is
loaded). Take mechanisms, not settings. Anyone posting a win rate without a matched
null is worth nothing here.

## 3. Pre-register, in writing, before running

- label and sweep name; span `screen` or `train` — **never `holdout`**
- expected trade count; under 30 is unrankable, under 200 is suggestive only
- the bar: edge over the **paired** null of `(1 + cost_share) / (1 + mult)` — +3.5
  points at a 10-point stop, +1.2 at 30
- the result that kills the hypothesis

## 4. Codex gate — before writing any code

`Skill(codex:rescue)` with the hypothesis, the mechanism, the cell, the pre-registered
bar, and: *where is this logic wrong, what confounds it, and what cheaper test answers
the same question?*

Record what Codex changed and what you rejected and why. If Codex is unreachable, write
that in the log — do not skip it silently. (`/codex:review` and
`/codex:adversarial-review` are user-typed only; ask for one when the diff is large.)

## 5. Implement lazily

- A new cell in `backtest/sweeps.py` plus a name in `SWEEPS` is usually the whole change.
- A new knob must go through `params.get()` at **every** read site. `min_rr_ratio` is
  read in both `backtest/rules.py` and `trading/risk.py`; overriding one leaves the
  other vetoing every trade.
- No new module, no abstraction, no refactor of code you are not testing.
- Never edit `ict/smc_patched.py`.

## 6. Run

```bash
.venv/bin/python main.py sweep smoke historical/ES-5y/glbx-mdp3-20210724-20260723.ohlcv-1m.dbn.zst
.venv/bin/python main.py sweep <name>  historical/ES-5y/glbx-mdp3-20210724-20260723.ohlcv-1m.dbn.zst
.venv/bin/python main.py sweep-report --top 20
```

Smoke first, every time. Long sweeps go in the background.

## 7. Judge — the traps that already cost published conclusions

- Never judge on raw win rate or raw P&L. `sweep-report` sorts on `edge_vs_null`, which
  is the **unpaired** null — a different bar, censored 15.8% against the strategy's
  5.8%. Use it to shortlist, then read `edge_vs_paired_null` and `z_vs_paired_null`
  straight out of `logs/experiments.jsonl` before believing any winner.
- `t > 3` and `n >= 200` are rules of thumb, not a multiple-comparisons correction.
  Nothing in the harness adjusts for the 65 configurations already tried, and the
  backlog itself was chosen after seeing which component came out positive. Treat a
  first pass as a candidate, never as a finding.
- Barrier exits only. `nonbarrier_pnl` is survivorship: a trade alive at 16:00 is one
  that was not stopped.
- **Any edge above +5 points is a bug until you find the cause.** Check the rejection
  funnel and the direction split, then
  `.venv/bin/python -m pytest tests/test_no_lookahead.py -v`.
- A result that needs `costs = 0` is not a result.

## 8. Log, then commit

- Prepend `## Experiment N — <the finding in one line>` to
  `docs/BACKTEST-RESULTS-LOG.md`: the question, the pre-registration, the table, the
  verdict, and what Codex said.
- Update "Where this left off" in CLAUDE.md so the next iteration starts oriented.
- Commit. Plain words, no achievement language.
- Then `Skill(codex:rescue)`: review the diff for correctness and look-ahead bias. Fix
  or record.

## Invariants

1. **2026-01 to 2026-07 stays unopened.** Screen and select on 2021-07 to 2024-12.
2. Never delete or rewrite a past experiment row. The record is append-only.
3. Trading costs stay on.
4. A negative result is a result. Log it with the same care as a positive one.
5. If two iterations in a row find nothing new to test, say so and stop rather than
   re-running variants of a spent question.
