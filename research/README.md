# research/

One-off analyses that produced a numbered entry in `docs/BACKTEST-RESULTS-LOG.md`.
They live in git for the same reason sweeps do: a result is only reproducible if
the exact thing that was run is recorded.

Run from the repository root. Output goes to `logs/exp27/`.

## Experiment 27 — stop width, and the resolver disagreement

```bash
python research/regen_exp26.py        # ~22 min, writes logs/exp27/exp26_trades.json
python research/rescore_stops.py      # the two stop-width tables
python research/resolver_check.py     # engine outcome vs Intrabar.first_touch
python research/quantify_defects.py   # sizes the two session-end faults
```

`regen_exp26.py` reproduces experiment 26's `concept:full_train` cell and saves
every trade, which the harness does not do — it stores summary rows only.
