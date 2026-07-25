"""Named, version-controlled sweep definitions.

Sweeps live here rather than in ad-hoc scripts for two reasons: a result is only
reproducible if the exact cell list is recorded, and the honest interpretation of
any winner depends on how many configurations were tried. Keeping the matrices in
git makes both auditable.

Sweeps are deliberately sequential and small rather than one big factorial. Each
answers one question while holding the rest fixed, so a result is interpretable
and the multiple-testing burden stays countable. A 6-cell sweep needs a far lower
significance hurdle than a 600-cell one.

Spans: screen on 2023, confirm on TRAIN, look at HOLDOUT once, at the end.
"""

from __future__ import annotations

# Screening span. 2023 is chosen precisely because every bias variant collapsed
# there — a grinding low-volatility uptrend. Screening on the hardest regime is
# adversarial: it kills configs that only work in easy conditions and cannot
# flatter a winner. ~370 trades at 15m, which clears the 200-trade bar, in about
# a sixth of the time of the full training span.
SCREEN = {"trade_start": "2023-01-01", "trade_end": "2023-12-31"}
TRAIN = {"trade_start": "2021-07-25", "trade_end": "2024-12-31"}
VALIDATE = {"trade_start": "2025-01-01", "trade_end": "2025-12-31"}
HOLDOUT = {"trade_start": "2026-01-01", "trade_end": "2026-07-23"}

SPANS = {"screen": SCREEN, "train": TRAIN, "validate": VALIDATE, "holdout": HOLDOUT}

# Premium/discount tells ICT *where* to enter inside a bias, not which way to
# trade. Measured on 2024 it votes bearish 97% of the time, so as a direction
# vote it is a standing short bias.
NO_PD = ("structure", "liquidity_draw", "raid")
STRUCT_LIQ = ("structure", "liquidity_draw")

# Research runs must not stop at the first 10% drawdown, or a 3.5-year sweep
# reports a few months and every cell looks the same.
RESEARCH = {"drawdown_limit_pct": 100.0}

# ICT sets the target from liquidity and lets R:R fall out. Turning the fallback
# off means "no liquidity to aim at, no trade", and the R:R floor drops to a veto
# rather than a filter that only keeps improbably distant targets.
ICT_GEOMETRY = {"tp_fallback_r": None, "tp_min_r": 0.5, "min_rr_ratio": 1.0}

BIAS_VARIANTS = {
    "all4_v3": {},                                                        # current default
    "all4_majority": {"bias_vote_rule": "majority"},
    "no_pd_v3": {"bias_factors_used": NO_PD, "bias_min_votes": 3},
    "no_pd_v2": {"bias_factors_used": NO_PD, "bias_min_votes": 2},
    "no_pd_plurality": {"bias_factors_used": NO_PD, "bias_vote_rule": "plurality"},
    "struct_liq_v2": {"bias_factors_used": STRUCT_LIQ, "bias_min_votes": 2},
}

BIAS_HYPOTHESES = {
    "all4_v3": "Baseline: all four factors, 3 must align. Premium/discount is in the "
               "vote, which measured 97% bearish in a rising market.",
    "all4_majority": "Majority of factors that actually voted, so a 2-1 split decides "
                     "instead of abstaining. Should trade more than 3-of-4.",
    "no_pd_v3": "Drop premium/discount from the vote but keep unanimity of the "
                "remaining three. Expected to be very selective.",
    "no_pd_v2": "Drop premium/discount, require 2 of 3. Measured the most balanced "
                "long/short split at 63% directional.",
    "no_pd_plurality": "Drop premium/discount, any margin decides. Most permissive; "
                       "tests whether more trades helps or just adds cost.",
    "struct_liq_v2": "Structure and liquidity draw only, both must agree. Tests "
                     "whether the raid factor contributes anything.",
}

GEOMETRY_HYPOTHESES = {
    "legacy_3r_fallback": "The old behaviour, for comparison: nearest liquidity at "
                          "1R+ else an arbitrary 3R target, R:R gate at 2.",
    "liq_only_min1r_rr2": "Liquidity targets only, no arbitrary fallback, but keep "
                          "the 2:1 gate. Isolates the fallback's effect.",
    "liq_only_min1r_rr1": "As above with R:R demoted to a 1.0 veto, so near targets "
                          "stop being discarded.",
    "liq_only_min05r_rr1": "Admit targets from 0.5R. ICT sizes the target from "
                           "liquidity and lets R:R fall out.",
    "liq_furthest_rr1": "Furthest qualifying liquidity rather than nearest. Wider "
                        "targets mean lower cost drag per R but a lower hit rate.",
    "liq_only_tight_stop": "Allow stops under the 2-point floor. Tighter stops raise "
                           "cost as a share of R, so this should look worse if the "
                           "1.02/stop_points relationship holds.",
}

GEOMETRY_VARIANTS = {
    "legacy_3r_fallback": {"tp_fallback_r": 3.0, "tp_min_r": 1.0, "min_rr_ratio": 2.0},
    "liq_only_min1r_rr2": {"tp_fallback_r": None, "tp_min_r": 1.0, "min_rr_ratio": 2.0},
    "liq_only_min1r_rr1": {"tp_fallback_r": None, "tp_min_r": 1.0, "min_rr_ratio": 1.0},
    "liq_only_min05r_rr1": {"tp_fallback_r": None, "tp_min_r": 0.5, "min_rr_ratio": 1.0},
    "liq_furthest_rr1": {"tp_fallback_r": None, "tp_min_r": 0.5, "min_rr_ratio": 1.0,
                         "tp_selection": "furthest"},
    "liq_only_tight_stop": {"tp_fallback_r": None, "tp_min_r": 0.5, "min_rr_ratio": 1.0,
                            "futures_min_sl_points": 1.0},
}

SWING_VARIANTS = {
    "swing_bias10": {"smc_swing_length": {"bias": 10, "swing": 10, "setup": 5, "entry": 5}},
    "swing_bias20": {"smc_swing_length": {"bias": 20, "swing": 15, "setup": 10, "entry": 5}},
    "swing_bias50": {"smc_swing_length": {"bias": 50, "swing": 20, "setup": 10, "entry": 5}},
}


def _cell(label, overrides, span=SCREEN, hypothesis="", **kw):
    """Build one experiment cell.

    `hypothesis` travels with the result into logs/experiments.jsonl, so months
    later a row still says why it was run rather than only what it scored. A
    result without its reasoning is not reusable evidence.
    """
    cell = {"label": label, "overrides": {**RESEARCH, **overrides},
            "hypothesis": hypothesis, **span}
    cell.update(kw)
    return cell


def bias_rules(span=SCREEN) -> list[dict]:
    """Which bias vote rule produces a tradeable, balanced signal?

    Geometry held at the ICT-faithful setting so the bias is what varies.
    """
    return [
        _cell(f"bias:{name}", {**ICT_GEOMETRY, **ov}, span,
              hypothesis=BIAS_HYPOTHESES.get(name, ""))
        for name, ov in BIAS_VARIANTS.items()
    ]


def geometry(span=SCREEN, bias: str = "no_pd_v2") -> list[dict]:
    """Given a bias rule, which stop and target geometry works?"""
    base = BIAS_VARIANTS[bias]
    return [
        _cell(f"geom:{name}", {**base, **ov}, span,
              hypothesis=GEOMETRY_HYPOTHESES.get(name, ""))
        for name, ov in GEOMETRY_VARIANTS.items()
    ]


def swing_lengths(span=SCREEN, bias: str = "no_pd_v2") -> list[dict]:
    """Does the backtest/live swing-length divergence matter?

    Live uses bias=50, backtests use bias=10. Note bias=50 needs 101 daily bars
    of warmup, roughly 145 calendar days, so early cells lose tradable history.
    """
    base = BIAS_VARIANTS[bias]
    return [
        _cell(f"swing:{name}", {**base, **ICT_GEOMETRY, **ov}, span)
        for name, ov in SWING_VARIANTS.items()
    ]


def timeframes(span=SCREEN, bias: str = "no_pd_v2") -> list[dict]:
    """5m versus 15m execution, with everything else held.

    Lower timeframes need less calendar time for the same statistical power:
    5m produces roughly 3x the setups per day.
    """
    base = {**BIAS_VARIANTS[bias], **ICT_GEOMETRY}
    return [
        _cell(f"tf:{tf}", base, span, entry_tf=tf)
        for tf in ("5min", "15min")
    ]


def strategies(span=SCREEN, bias: str = "no_pd_v2") -> list[dict]:
    """Confluence scoring versus the two concrete ICT models."""
    base = {**BIAS_VARIANTS[bias], **ICT_GEOMETRY}
    return [
        _cell(f"strat:{name}", base, span, strategy=name)
        for name in ("default", "ict_2022", "silver_bullet")
    ]


def invert(span=SCREEN) -> list[dict]:
    """Is the entry signal anti-predictive, or merely edgeless?

    Measured on the 2023 screen, three bias variants sit 3.2 to 3.6 sigma BELOW
    their own random-walk benchmark on ~370 trades. That is not noise — it is
    exploitable information pointing the wrong way. If flipping the direction
    lands materially above the benchmark, the entry rule has a sign or lag error
    and that is the bug. If it merely mirrors to roughly zero edge, the signal
    carries nothing and the geometry is doing all the work.

    Pairs each bias rule with its inverse so the comparison is like for like.
    """
    cells = []
    for name in ("all4_majority", "no_pd_v2", "no_pd_plurality"):
        base = {**ICT_GEOMETRY, **BIAS_VARIANTS[name]}
        cells.append(_cell(f"inv:{name}_normal", base, span,
                           hypothesis=f"Control arm for the inversion test on {name}."))
        cells.append(_cell(f"inv:{name}_flipped", {**base, "invert_bias": True}, span,
                           hypothesis=f"{name} with the bias direction flipped. Beating "
                                      f"the benchmark here means a sign or lag error."))
    return cells


def smoke(span=None) -> list[dict]:
    """Two cells over one month — verifies the harness before a long run.

    Worth running first every time. macOS spawns worker processes rather than
    forking, so anything that breaks re-import of the entry point shows up here
    in a minute instead of an hour into a real sweep.
    """
    span = {"trade_start": "2024-03-01", "trade_end": "2024-04-01"}
    return [
        _cell("smoke:old_default", {}, span),
        _cell("smoke:no_pd_v2_ict", {**ICT_GEOMETRY, **BIAS_VARIANTS["no_pd_v2"]}, span),
    ]


SWEEPS = {
    "smoke": smoke,
    "invert": invert,
    "bias": bias_rules,
    "geometry": geometry,
    "swing": swing_lengths,
    "timeframes": timeframes,
    "strategies": strategies,
}


def get_sweep(name: str, span: str = "screen") -> list[dict]:
    """Build a named sweep over a named span.

    Screening happens on 2023, selection is confirmed on train, and holdout is
    looked at once at the very end.
    """
    if name not in SWEEPS:
        raise ValueError(f"Unknown sweep {name!r}. Choose from: {', '.join(sorted(SWEEPS))}")
    if span not in SPANS:
        raise ValueError(f"Unknown span {span!r}. Choose from: {', '.join(SPANS)}")
    return SWEEPS[name](SPANS[span])
