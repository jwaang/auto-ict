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

# Half-year screen for lower timeframes. 5m produces roughly 3x the setups per
# calendar day, so six months at 5m yields more trades than a year at 15m while
# costing about half the wall clock. Trade count is the binding constraint on
# reading a win rate, not calendar length.
SCREEN_H2 = {"trade_start": "2023-07-01", "trade_end": "2023-12-31"}

SPANS = {"screen": SCREEN, "screen_h2": SCREEN_H2, "train": TRAIN,
         "validate": VALIDATE, "holdout": HOLDOUT}

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
    """The two concrete ICT models against the confluence path.

    These are the last untested code path. They bypass `decide_trade` entirely and
    require a temporal sequence — liquidity sweep, then market structure shift, then
    FVG entry, in causal order — and they gate on kill zones. That makes them far
    more selective than anything tested so far, and selectivity is the one remaining
    avenue the evidence supports: fewer, better trades directly attack a cost drag
    running 10-28% of R.

    Deliberately NOT given ICT_GEOMETRY. The strategies carry their own hardcoded
    _MIN_RR (3.0 for the 2022 model, 2.0 for Silver Bullet) and their own 3R
    fallback in `common.find_take_profit`, and they read no params — so passing
    geometry overrides would loosen only the engine-level risk veto while leaving
    their internal gates untouched, which is a muddle rather than a test. They run
    as designed; the bias fixes still reach them through `common.get_htf_bias`.
    """
    bias_only = BIAS_VARIANTS[bias]
    return [
        _cell("strat:default", {**bias_only, **ICT_GEOMETRY}, span, strategy="default",
              hypothesis="Control: the confluence path with the geometry used "
                         "throughout the other sweeps."),
        _cell("strat:ict_2022", bias_only, span, strategy="ict_2022",
              hypothesis="Sweep then MSS then FVG, kill-zone gated, internal 3:1 R:R "
                         "floor. Should trade rarely; the question is whether "
                         "selectivity buys quality."),
        _cell("strat:silver_bullet", bias_only, span, strategy="silver_bullet",
              hypothesis="Same sequence confined to three one-hour windows with a "
                         "2:1 floor. The most selective configuration available."),
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


def directions(span=SCREEN, bias: str = "no_pd_v2") -> list[dict]:
    """Are longs and shorts equally broken, or is the damage one-sided?

    On the 2023 screen under identical rules, longs won 22.9% and shorts 31.1%.
    Flipping the bias moved longs to 39.4% while shorts stayed near 30%, so the
    anti-edge is concentrated on the long side. Isolating each side says whether
    that is a real asymmetry in the entry logic or an artefact of the pairing.
    """
    base = {**ICT_GEOMETRY, **BIAS_VARIANTS[bias]}
    return [
        _cell("dir:both", base, span,
              hypothesis="Control: both sides enabled, current rules."),
        _cell("dir:long_only", {**base, "allowed_directions": ("LONG",)}, span,
              hypothesis="Longs only. If this is far worse than shorts-only, the "
                         "long entry path has a specific defect."),
        _cell("dir:short_only", {**base, "allowed_directions": ("SHORT",)}, span,
              hypothesis="Shorts only. Measured near 31% in both arms of the "
                         "inversion test, suggesting shorts are merely edgeless."),
        _cell("dir:ote_direction_off", {**base, "ote_require_direction": False}, span,
              hypothesis="Revert the OTE direction check to measure what that bug "
                         "was contributing. Expect worse if the fix is right."),
    ]


def triggers(span=SCREEN, bias: str = "no_pd_v2") -> list[dict]:
    """Does a causally clean trigger do better than the zone finders?

    Research flagged FVG and CISD as the only ICT concepts that cannot read future
    data. The current entry rests on order blocks, which are defined retroactively
    ("the last down candle before the up move"), so any edge they show is suspect.
    CISD reads closed bodies against an opening price known beforehand.

    The zone finders put longs 15.5 points below their own benchmark. If CISD lands
    materially better, the trigger was the problem. If it lands at its benchmark
    too, the bias is what carries no information and no trigger will rescue it.
    """
    base = {**ICT_GEOMETRY, **BIAS_VARIANTS[bias]}
    cells = [
        _cell("trig:levels", base, span,
              hypothesis="Control: the existing FVG/OB zone finders."),
    ]
    for age in (5, 10, 20):
        cells.append(_cell(
            f"trig:cisd_age{age}", {**base, "entry_trigger": "cisd", "cisd_max_age": age},
            span,
            hypothesis=f"CISD entry, actionable for {age} bars after the flip. Longer "
                       f"windows trade more but enter further from the reference.",
        ))
    cells.append(_cell(
        "trig:cisd_short_only",
        {**base, "entry_trigger": "cisd", "allowed_directions": ("SHORT",)}, span,
        hypothesis="CISD shorts only. Shorts were the less broken side under the "
                   "zone finders, so this separates trigger from direction."))
    return cells


def execution_tf(span=SCREEN_H2, bias: str = "no_pd_v2") -> list[dict]:
    """Test ICT's documented execution ladder, which the code has never used.

    Every run so far executes on 15m — but 15m is ICT's *array* timeframe. His
    day-trade ladder is 1H bias, 15m context, **5m execution**, and his stated
    method for improving R:R is to shrink the stop by dropping timeframes while
    leaving the target unchanged. That combination has never been tested here.

    It is the one configuration where favourable excursion measured in R could
    exceed target R rather than sitting at the 0.70 it has held at across every
    trigger, direction and bias rule so far. The headwind is quantified: cost drag
    is 1.02/stop_points, so a 3-point stop gives away 34% of R.

    Run on a half-year span so 5m stays inside a sane wall clock; 5m still yields
    more trades over six months than 15m does over twelve.
    """
    base = {**ICT_GEOMETRY, **BIAS_VARIANTS[bias]}
    return [
        _cell("exec:15m_control", base, span, entry_tf="15min",
              hypothesis="Control on the same half-year span so the 5m cells are "
                         "comparable rather than being judged against a full year."),
        _cell("exec:5m_levels", base, span, entry_tf="5min",
              hypothesis="ICT's execution timeframe with the zone finders. Tighter "
                         "structural stop, target still from HTF liquidity."),
        _cell("exec:5m_cisd", {**base, "entry_trigger": "cisd"}, span, entry_tf="5min",
              hypothesis="5m execution with CISD, the best trigger so far by edge "
                         "over benchmark and the only causally clean one."),
    ]


def strategies_5m(span=SCREEN_H2, bias: str = "no_pd_v2") -> list[dict]:
    """The ICT strategies on an execution timeframe they can actually use.

    Silver Bullet confines the entire sweep-then-MSS-then-FVG sequence to a single
    one-hour window. At 15m that window holds **4 bars**, while the sequence needs
    sweep_idx < choch_idx < fvg_idx and an FVG needs 3 closed candles — roughly 5-6
    bars minimum. So Silver Bullet is not selective at 15m, it is **structurally
    impossible**, which is why it produced exactly zero trades over a full year.

    Research agrees: Silver Bullet is a 15m *parent* with 1m/3m/5m execution. At 5m
    the window holds 12 bars and the sequence can fit.
    """
    bias_only = BIAS_VARIANTS[bias]
    return [
        _cell("strat5:ict_2022", bias_only, span, strategy="ict_2022", entry_tf="5min",
              hypothesis="The 2022 model on 5m execution. At 15m it managed 23 trades "
                         "in a year, too few to read."),
        _cell("strat5:silver_bullet", bias_only, span, strategy="silver_bullet",
              entry_tf="5min",
              hypothesis="Silver Bullet on 5m, where its one-hour window holds 12 bars "
                         "instead of 4 and the sequence can physically fit."),
    ]


def silver_bullet_scope(span=SCREEN_H2, bias: str = "no_pd_v2") -> list[dict]:
    """How much of the sequence must sit inside the Silver Bullet hour?

    Confining the whole chain makes the setup arithmetically impossible — zero
    trades over a full year at both 15m and 5m, with 220 of 220 in-window
    directional bars failing. Research describes the rule as the first FVG formed
    inside the window aligned with HTF bias and an MSS, so the sweep at least may
    precede it.

    Run at 5m, where the hour holds 12 bars rather than 4.
    """
    base = BIAS_VARIANTS[bias]
    return [
        _cell(f"sbscope:{scope}", {**base, "sb_window_scope": scope}, span,
              strategy="silver_bullet", entry_tf="5min", hypothesis=note)
        for scope, note in (
            ("all", "The original reading: sweep, MSS and FVG all in-window. "
                    "Expected to stay at zero — kept as the control."),
            ("mss_fvg", "MSS and FVG in-window, sweep may precede. Closest to the "
                        "documented rule."),
            ("fvg", "Only the FVG in-window. Loosest reading; most trades."),
        )
    ]


# Training-span slices that the 2023 H2 screen never touched. Re-running the screen
# window would not be new evidence.
SB_OUT_OF_SCREEN = (
    ("2021-08-01", "2022-07-31"),
    ("2022-08-01", "2023-06-30"),
    ("2024-01-01", "2024-12-31"),
)


def silver_bullet_extend(span=None, bias: str = "no_pd_v2") -> list[dict]:
    """Grow the Silver Bullet sample on data the screen did not see.

    The `fvg` window scope is the first configuration in this project to show a
    positive edge over its own benchmark (+15.0 points), profit factor above 1
    (1.60), positive expectancy (+0.40R) and single-digit drawdown (9%).

    It is also 25 trades, at z = 1.65, with a 95% confidence interval on the win
    rate spanning 25% to 63% — an interval that contains the benchmark. Against 34
    configurations tried, the bar for believing a data-mined result is t > 3, which
    25 trades cannot reach even in principle.

    So this is not a result yet, it is a hypothesis with a sample size problem. These
    three slices cover roughly three years the screen never used, at about 50 trades
    a year, which should bring the pooled sample near 175. Still short of 200, and
    the holdout stays untouched.
    """
    base = {**BIAS_VARIANTS[bias], "sb_window_scope": "fvg"}
    return [
        _cell(f"sbext:{start[:7]}", base,
              {"trade_start": start, "trade_end": end},
              strategy="silver_bullet", entry_tf="5min",
              hypothesis=f"Out-of-screen slice {start} to {end}. Does the +15 point "
                         f"edge survive on data that did not select it?")
        for start, end in SB_OUT_OF_SCREEN
    ]


def concept_decomposition(span=TRAIN, bias: str = "all4_majority") -> list[dict]:
    """Which ICT concept carries the edge, if any of them do?

    Over the full training span the best bias config sits exactly on its null:
    +0.5 win-rate points at z 0.33 over 878 barrier trades. Zero total edge can
    mean every concept is noise, or that some are positive and some negative and
    they cancel — and the confluence score, which adds them up, has no
    predictive slope, which fits cancellation.

    The entry waterfall records which concept fired as `setup_type`, so one run
    decomposes it. `_setup_split` scores each type against its own matched null
    rather than a shared one, because each has its own stop and target
    distribution.

    Pre-registered before looking: with 64 configurations already tried, a
    concept is worth pursuing only at z > 3 and 200+ barrier trades. Anything
    less is noise at this point in the search, and the 2026 holdout stays shut
    either way.
    """
    return [
        _cell("concept:full_train", {**ICT_GEOMETRY, **BIAS_VARIANTS[bias]}, span,
              hypothesis="Decompose the entry waterfall by setup type over the "
                         "full training span. Each type scored against its own "
                         "matched null. Looking for one concept above +3.5 points, "
                         "the breakeven bar at a 10-point stop.",
              entry_tf="15min"),
    ]


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
    "directions": directions,
    "triggers": triggers,
    "execution_tf": execution_tf,
    "strategies_5m": strategies_5m,
    "sb_scope": silver_bullet_scope,
    "sb_extend": silver_bullet_extend,
    "concepts": concept_decomposition,
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
