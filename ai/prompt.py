"""Claude API prompt builder for ICT trade analysis."""

SYSTEM_PROMPT = """You are an expert ICT (Inner Circle Trader) analyst performing paper trade analysis.
You analyze OHLC price data with pre-computed ICT levels and make trade decisions.

## ICT Rules You MUST Follow

1. **Market Structure First** — Higher timeframe bias determines direction. Only look for longs in bullish structure, shorts in bearish.
2. **Kill Zone Entries Only** — For equities/forex, only enter during London (2-5am ET), New York (7-10am ET), or Asian (7-10pm ET) sessions. Crypto is exempt.
3. **FVG + OB Confluence** — The highest probability entries occur where Fair Value Gaps overlap with Order Blocks.
4. **OTE Zone** — Enter at the 61.8%-79% Fibonacci retracement (sweet spot = 70.5%). This is where institutions re-enter after displacement.
5. **Displacement Required** — Only trade after seeing a displacement move (impulsive candle with body > 2x ATR). No displacement = no entry.
6. **Liquidity Sweep Before Entry** — Look for price to sweep liquidity (take out swing high/low stops) before reversing. The sweep is the "trap" that creates the entry.
7. **Premium/Discount** — Buy in discount (below 50% of range), sell in premium (above 50% of range). Never buy in premium or sell in discount.
8. **Risk Management** — Max 1-2% of account per trade. Minimum 2:1 reward-to-risk ratio. Stop loss placed beyond the order block.
9. **Power of Three** — Identify the pattern: Accumulation (range) → Manipulation (liquidity sweep/fake breakout) → Distribution (true move).
10. **No Chasing** — Only enter on pullbacks to identified levels. If price has already moved, wait for the next setup.
11. **Previous Day/Week High/Low (PDH/PDL/PWH/PWL)** — These are primary liquidity targets where stops cluster from the previous session. Use them as take-profit targets or as manipulation levels to look for entries after a sweep. An unbroken PDH/PDL is a magnet for price.
12. **Market Structure Shift (MSS)** — A CHoCH accompanied by a displacement candle. This is a STRONGER signal than a plain CHoCH because it shows institutional commitment. Weight MSS much higher than regular CHoCH when evaluating reversals.
13. **Consequent Encroachment (CE)** — The 50% midpoint of any FVG. This is a key reaction level where price often reverses. If price taps the CE of an FVG and rejects, that is a high-probability entry signal. CE levels are provided for each FVG.
14. **Silver Bullet Windows** — Narrow 1-hour execution windows (3-4am ET London, 10-11am ET NY AM, 2-3pm ET NY PM) where FVGs form with high reliability. Entries during Silver Bullet windows in alignment with bias are highest probability. The NY AM window (10-11am) is statistically the best.

## Decision Framework

1. Check HTF bias — if neutral, prefer NO_TRADE
2. Verify displacement occurred on setup/entry timeframe
3. Identify FVG + OB confluence zone
4. Confirm price is in OTE zone or approaching it
5. Check if liquidity was swept (manipulation phase complete)
6. Verify premium/discount alignment with bias
7. Set SL beyond the order block, TP at next liquidity target
8. Calculate R:R — must be >= 2:1

If ANY of these fail, output NO_TRADE with specific reasoning about which condition failed.

## Output Format

You have THREE decision types:

1. **LONG / SHORT** — Price is AT a valid entry level RIGHT NOW with confirmation present. Immediate entry.
2. **CONDITIONAL_LONG / CONDITIONAL_SHORT** — Setup is valid but price hasn't pulled back to entry zones yet. Define zones to watch and what confirmation is needed. This is the most common output when a setup exists but price isn't at the level.
3. **NO_TRADE** — No valid setup exists, or conditions are too unclear.

Respond with ONLY valid JSON (no markdown, no explanation outside the JSON):

{
  "decision": "LONG" | "SHORT" | "CONDITIONAL_LONG" | "CONDITIONAL_SHORT" | "NO_TRADE",
  "confidence": <1-10>,
  "reasoning": "<Detailed explanation citing specific ICT concepts, price levels, and why>",
  "htf_bias": "bullish" | "bearish" | "neutral",
  "setup_type": "<e.g. 'OB+FVG confluence at OTE' or 'Conditional pullback to 4H OB'>",
  "ict_concepts_used": ["<list of ICT concepts>"],
  "invalidation": "<What price action invalidates the entire setup (e.g. '4H close below $67,400')>",

  "entry_price": <float | null>,
  "stop_loss": <float | null>,
  "take_profit": <float | null>,
  "risk_reward_ratio": <float | null>,

  "entry_zones": [
    {
      "zone_low": <float>,
      "zone_high": <float>,
      "zone_type": "<OB | FVG | OB+FVG | OTE>",
      "zone_timeframe": "<4h | 1h | 15m>",
      "priority": <1=best, 2=good, 3=acceptable>,
      "stop_loss": <float>,
      "take_profit_1": <float>,
      "take_profit_2": <float | null>,
      "risk_reward": <float>,
      "confirmation_needed": "<What signal to look for on the CONFIRMATION timeframe (one TF below the zone TF). 4H zone needs 1H confirmation. 1H zone needs 15M confirmation.>",
      "reasoning": "<Why this specific zone>"
    }
  ]
}

For LONG/SHORT: populate entry_price/stop_loss/take_profit directly, entry_zones can be empty.
For CONDITIONAL: entry_price/stop_loss/take_profit should be null, populate entry_zones instead.
For NO_TRADE: all price fields null, entry_zones empty.

entry_zones should be ordered by priority (1=best R:R and confluence, 2=good, 3=acceptable).
Each zone must independently pass risk management: R:R >= 2:1, SL beyond the OB."""


def build_messages(ict_context: dict, account_state: dict) -> list[dict]:
    """Build the messages list for the Claude API call.

    Args:
        ict_context: Complete ICT analysis from confluence.analyze_multi_timeframe()
        account_state: Current account balance and positions

    Returns:
        List of message dicts for the Anthropic API
    """
    user_prompt = _build_user_prompt(ict_context, account_state)
    return [
        {"role": "user", "content": user_prompt},
    ]


def get_system_prompt() -> str:
    """Return the system prompt."""
    return SYSTEM_PROMPT


def _build_user_prompt(ctx: dict, account: dict) -> str:
    """Build the user message with all ICT context data."""
    ticker = ctx.get("ticker", "UNKNOWN")
    analyses = ctx.get("analyses", {})

    bias_data = analyses.get("bias", {})
    setup_data = analyses.get("setup", {})
    entry_data = analyses.get("entry", {})

    sections = []

    # Header
    current_price = entry_data.get("current_price") or setup_data.get("current_price", 0)
    sections.append(f"Analyze {ticker} for a potential ICT trade setup.")
    sections.append(f"\n== CURRENT PRICE ==\n${current_price:.2f}")
    sections.append(f"Is Crypto: {ctx.get('is_crypto', False)}")

    # HTF Bias
    sections.append("\n== HIGHER TIMEFRAME BIAS (Daily) ==")
    sections.append(f"Market Structure Bias: {bias_data.get('bias', 'unknown')}")
    breaks = bias_data.get("structure_breaks", [])
    if breaks:
        recent_breaks = breaks[-5:]
        for b in recent_breaks:
            sections.append(f"  {b['type']} {b['direction']} at {b['level']:.2f} ({b['timestamp']})")
    swings = bias_data.get("swings", [])
    sh = [s for s in swings if s["type"] == "swing_high"][-5:]
    sl = [s for s in swings if s["type"] == "swing_low"][-5:]
    sh_levels = [f"${s['level']:.2f}" for s in sh]
    sl_levels = [f"${s['level']:.2f}" for s in sl]
    sections.append(f"Swing Highs: {sh_levels}")
    sections.append(f"Swing Lows: {sl_levels}")

    # Swing TF (4H)
    swing_data = analyses.get("swing", {})
    if swing_data:
        sections.append("\n== SWING TIMEFRAME (4H) ==")
        _append_ict_levels(sections, swing_data)

    # Setup TF
    sections.append("\n== SETUP TIMEFRAME (1H) ==")
    _append_ict_levels(sections, setup_data)

    # Entry TF
    sections.append("\n== ENTRY TIMEFRAME (15M) ==")
    _append_ict_levels(sections, entry_data)

    # Confluences
    confluences = ctx.get("confluences", [])
    score = ctx.get("confluence_score", 0)
    sections.append(f"\n== CONFLUENCES (Score: {score}/100) ==")
    if confluences:
        for c in confluences:
            sections.append(f"  {c['type']}: {c.get('direction', 'N/A')}")
    else:
        sections.append("  No confluences detected")

    # Account state
    sections.append(f"\n== ACCOUNT STATE ==")
    sections.append(f"Balance: ${account.get('balance', 0):,.2f}")
    sections.append(f"Open positions: {account.get('open_position_count', 0)}")
    max_risk = account.get("balance", 0) * 0.01
    sections.append(f"Max risk this trade: ${max_risk:,.2f} (1% of balance)")

    # Recent candles
    recent = ctx.get("recent_entry_candles", [])
    if recent:
        sections.append(f"\n== RECENT ENTRY CANDLES (15M, last {len(recent)}) ==")
        sections.append(f"{'Timestamp':<25} {'Open':>10} {'High':>10} {'Low':>10} {'Close':>10}")
        for c in recent:
            ts = c["timestamp"][:19] if len(c["timestamp"]) > 19 else c["timestamp"]
            sections.append(f"{ts:<25} {c['open']:>10.2f} {c['high']:>10.2f} {c['low']:>10.2f} {c['close']:>10.2f}")

    return "\n".join(sections)


def _append_ict_levels(sections: list[str], data: dict):
    """Append ICT level details for a timeframe."""
    # FVGs
    unfilled = data.get("unfilled_fvgs", [])
    sections.append(f"Fair Value Gaps (unfilled): {len(unfilled)}")
    for f in unfilled[-5:]:
        sections.append(f"  {f['type']} FVG: {f['bottom']:.2f} - {f['top']:.2f} (mid: {f['midpoint']:.2f})")

    # Order Blocks
    obs = data.get("unmitigated_obs", [])
    sections.append(f"Order Blocks (unmitigated): {len(obs)}")
    for ob in obs[-5:]:
        strength = f", strength: {ob['strength_pct']}%" if ob.get("strength_pct") else ""
        disp = f", disp: {ob['displacement_body_atr']:.1f}x" if ob.get("displacement_body_atr") else ""
        sections.append(f"  {ob['type']} OB: {ob['low']:.2f} - {ob['high']:.2f} (mid: {ob['midpoint']:.2f}{disp}{strength})")

    # Displacements
    disps = data.get("displacements", [])
    sections.append(f"Displacements: {len(disps)}")
    for d in disps[-3:]:
        sections.append(f"  {d['direction']} displacement at {d['timestamp']} ({d['body_atr_ratio']}x ATR, {d['consecutive_count']} consecutive)")

    # Liquidity
    liq = data.get("liquidity_zones", [])
    sections.append(f"Liquidity Zones: {len(liq)}")
    for z in liq:
        swept = " [SWEPT]" if z.get("swept") else ""
        sections.append(f"  {z['type']}: {z['level']:.2f} ({z['touch_count']} touches){swept}")

    # Premium/Discount
    pd_zone = data.get("premium_discount", {})
    sections.append(f"Premium/Discount: {pd_zone.get('zone', 'N/A')} (equilibrium: {pd_zone.get('equilibrium', 'N/A')})")

    # OTE
    ote = data.get("ote", {})
    if ote.get("valid"):
        sections.append(f"OTE Zone ({ote['direction']}): {ote['ote_low']:.2f} - {ote['ote_high']:.2f} (sweet spot: {ote['sweet_spot']:.2f})")
    else:
        sections.append("OTE Zone: Not available")

    # Kill zone
    kz = data.get("kill_zone")
    sections.append(f"Active Kill Zone: {kz or 'None (outside kill zones)'}")

    # Silver Bullet window
    sb = data.get("silver_bullet")
    if sb:
        sections.append(f"Silver Bullet Window: {sb}")

    # Previous Day/Week High/Low
    pdhl = data.get("previous_high_low", {})
    if pdhl:
        parts = []
        if pdhl.get("pdh") is not None:
            parts.append(f"PDH=${pdhl['pdh']:.2f}{'[BROKEN]' if pdhl.get('pdh_broken') else ''}")
        if pdhl.get("pdl") is not None:
            parts.append(f"PDL=${pdhl['pdl']:.2f}{'[BROKEN]' if pdhl.get('pdl_broken') else ''}")
        if pdhl.get("pwh") is not None:
            parts.append(f"PWH=${pdhl['pwh']:.2f}{'[BROKEN]' if pdhl.get('pwh_broken') else ''}")
        if pdhl.get("pwl") is not None:
            parts.append(f"PWL=${pdhl['pwl']:.2f}{'[BROKEN]' if pdhl.get('pwl_broken') else ''}")
        if parts:
            sections.append(f"Previous High/Low: {', '.join(parts)}")

    # Retracement
    ret = data.get("retracement", {})
    if ret and ret.get("direction") != "neutral":
        ote_tag = " [IN OTE]" if ret.get("in_ote") else ""
        sections.append(f"Retracement: {ret['direction']} {ret.get('current_retracement_pct', 0):.1f}% (deepest: {ret.get('deepest_retracement_pct', 0):.1f}%){ote_tag}")

    # Market Structure Shifts
    mss = data.get("mss_events", [])
    if mss:
        sections.append(f"Market Structure Shifts: {len(mss)}")
        for m in mss[-3:]:
            sections.append(f"  MSS {m['direction']} at {m['timestamp']} (displacement: {m['displacement_ratio']:.1f}x ATR)")
