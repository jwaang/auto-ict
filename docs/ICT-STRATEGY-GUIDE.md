# ICT (Inner Circle Trader) Strategy Guide

A comprehensive reference for the ICT trading methodology developed by Michael J. Huddleston. This guide covers every core concept, detection rule, and execution framework used by the ICT Paper Trading Simulator.

---

## Table of Contents

1. [What is ICT?](#1-what-is-ict)
2. [Core Philosophy](#2-core-philosophy)
3. [Market Structure](#3-market-structure)
4. [Liquidity](#4-liquidity)
5. [Order Blocks (OB)](#5-order-blocks-ob)
6. [Fair Value Gaps (FVG)](#6-fair-value-gaps-fvg)
7. [Displacement](#7-displacement)
8. [Premium & Discount Zones](#8-premium--discount-zones)
9. [Optimal Trade Entry (OTE)](#9-optimal-trade-entry-ote)
10. [Kill Zones & Sessions](#10-kill-zones--sessions)
11. [Power of Three](#11-power-of-three)
12. [Breaker Blocks](#12-breaker-blocks)
13. [Mitigation Blocks](#13-mitigation-blocks)
14. [Silver Bullet Strategy](#14-silver-bullet-strategy)
15. [Judas Swing](#15-judas-swing)
16. [Unicorn Model](#16-unicorn-model)
17. [Multi-Timeframe Analysis](#17-multi-timeframe-analysis)
18. [Risk Management](#18-risk-management)
19. [Complete Trade Execution Framework](#19-complete-trade-execution-framework)
20. [Algorithmic Detection Rules](#20-algorithmic-detection-rules)
21. [Glossary](#21-glossary)

---

## 1. What is ICT?

ICT (Inner Circle Trader) is a trading methodology developed by Michael J. Huddleston that focuses on understanding market movements from the perspective of institutional traders ("smart money") rather than relying on traditional technical indicators like moving averages, RSI, or MACD.

The fundamental premise: retail traders consistently lose because they trade against institutional order flow. By learning to identify where institutions place orders and how they manipulate liquidity, a trader can position on the same side as the dominant market participants.

ICT does NOT use:
- Moving averages, Bollinger Bands, or oscillators
- Traditional support/resistance
- Candlestick pattern names (doji, hammer, etc.)
- Volume indicators (though volume confirms)

ICT DOES use:
- Raw price action (OHLC candles only)
- Market structure (swing highs/lows)
- Order flow concepts (where institutional orders sit)
- Time-based analysis (kill zones, sessions)
- Fibonacci retracement (for OTE zones only)

---

## 2. Core Philosophy

### Smart Money vs. Retail Money

ICT posits that markets are driven by "smart money" — banks, hedge funds, central banks, and market makers — who operate fundamentally differently from retail traders:

| Retail Traders | Smart Money |
|---------------|-------------|
| Buy breakouts above resistance | Engineer false breakouts to fill orders |
| Place stops at obvious levels | Target those stops for liquidity |
| Chase momentum | Create momentum to distribute positions |
| Use lagging indicators | Read raw order flow and price action |
| Trade any time of day | Execute during specific kill zones |

### The Three Phases of Every Move

Every significant market move follows three phases:

1. **Accumulation** — Smart money quietly builds a position during consolidation
2. **Manipulation** — Price is pushed against the intended direction to sweep liquidity (stop losses), trapping retail traders
3. **Distribution** — The true directional move begins as smart money distributes positions to retail traders entering late

This is the "Power of Three" — the foundational narrative of every ICT setup.

### Engineering Liquidity

Smart money needs liquidity to fill large orders. They cannot simply "buy 10,000 contracts" without moving the market against themselves. So they engineer situations where retail traders provide that liquidity:

- They push price above resistance to trigger buy stops, then sell into those orders
- They push price below support to trigger sell stops, then buy into those orders
- They create obvious patterns (double tops/bottoms, trendlines) specifically so retail traders place predictable stops

Understanding this changes everything about how you read a chart.

---

## 3. Market Structure

Market structure is the foundation of ICT analysis. It determines your directional bias before anything else.

### Swing Highs and Swing Lows

A **swing high** is a candle whose high is greater than the highs of N candles on both sides (typically N=5).

A **swing low** is a candle whose low is less than the lows of N candles on both sides.

These swings create the structural framework of the market.

### Trend Identification

| Trend | Pattern | Swing Sequence |
|-------|---------|---------------|
| Bullish | Higher Highs + Higher Lows | HH → HL → HH → HL |
| Bearish | Lower Highs + Lower Lows | LH → LL → LH → LL |
| Ranging | No clear progression | Mixed |

### Break of Structure (BOS)

A **BOS** confirms the continuation of the existing trend:

- **Bullish BOS**: Price breaks above a previous swing high (Higher High) in an uptrend
- **Bearish BOS**: Price breaks below a previous swing low (Lower Low) in a downtrend

A BOS is a **continuation** signal — the trend is intact and likely to continue.

### Change of Character (CHoCH) / Market Structure Shift (MSS)

A **CHoCH** signals a potential trend reversal:

- **Bullish CHoCH**: In a downtrend, price breaks above a previous Lower High — the first Higher High, signaling potential trend reversal to bullish
- **Bearish CHoCH**: In an uptrend, price breaks below a previous Higher Low — the first Lower Low, signaling potential trend reversal to bearish

A CHoCH is the **earliest signal** of a trend change. It does not guarantee reversal, but it shifts the bias.

### How to Use Market Structure

1. **Always determine bias on the higher timeframe first** (daily or weekly)
2. In bullish structure, ONLY look for longs
3. In bearish structure, ONLY look for shorts
4. If structure is ranging/neutral, prefer no trade
5. A CHoCH on the daily timeframe overrides lower timeframe signals

### Detection Rule (Used in This System)

```
Swing High: candle[i].high > max(candle[i-N:i].high) AND candle[i].high > max(candle[i+1:i+N+1].high)
Swing Low:  candle[i].low  < min(candle[i-N:i].low)  AND candle[i].low  < min(candle[i+1:i+N+1].low)
```

Where N = lookback window (default 5).

---

## 4. Liquidity

Liquidity is arguably the single most important concept in ICT. It explains *why* price moves where it does.

### What is Liquidity?

Liquidity in ICT refers to clusters of pending orders (stop losses, limit orders) sitting at predictable price levels. These order clusters are "fuel" that smart money needs to fill their large positions.

### Types of Liquidity

**Buy-Side Liquidity (BSL)**
- Located **above** swing highs, equal highs, and resistance levels
- Consists of: buy stop orders (short sellers' stop losses), buy limit orders (breakout entries)
- When price sweeps BSL, it triggers buying, which smart money sells into

**Sell-Side Liquidity (SSL)**
- Located **below** swing lows, equal lows, and support levels
- Consists of: sell stop orders (long traders' stop losses), sell limit orders (breakdown entries)
- When price sweeps SSL, it triggers selling, which smart money buys into

### Where Liquidity Accumulates

| Level Type | Liquidity Type | Who Gets Trapped |
|-----------|---------------|-----------------|
| Previous swing highs | Buy-side (BSL) | Short sellers' stops |
| Previous swing lows | Sell-side (SSL) | Long traders' stops |
| Equal highs (double/triple tops) | Strong BSL | Many shorts + breakout buyers |
| Equal lows (double/triple bottoms) | Strong SSL | Many longs + breakdown sellers |
| Round numbers ($100, $50,000) | Both sides | Institutional limit orders |
| Session highs/lows | Both sides | Intraday traders |
| Trendlines | Both sides | Trendline traders |

### Liquidity Sweeps (Stop Hunts)

A **liquidity sweep** occurs when price moves just beyond a key level, triggers the clustered orders, then quickly reverses. This is the "manipulation" phase.

Characteristics of a sweep:
- Price **wicks through** the level but **closes back** on the other side
- Often occurs with a long wick (showing rejection)
- Typically happens during kill zone hours
- Followed by displacement in the opposite direction

**This is the single most important pre-condition for an ICT entry.** Without a sweep, the setup is incomplete.

### Detection Rule

```
Buy-side sweep: candle.high > liquidity_level AND candle.close < liquidity_level
Sell-side sweep: candle.low < liquidity_level AND candle.close > liquidity_level
```

---

## 5. Order Blocks (OB)

Order Blocks represent zones where institutional orders were placed. They are the ICT equivalent of "support and resistance" — but with a specific, mechanical definition.

### Definition

- **Bullish Order Block**: The last **bearish (down-close) candle** before a strong bullish displacement move
- **Bearish Order Block**: The last **bullish (up-close) candle** before a strong bearish displacement move

The OB zone spans the candle's full range (high to low). The midpoint (50% level, called the "mean threshold") is the highest-probability reaction point.

### What Makes an OB Valid

Not every opposing candle before a move is a valid OB. Valid OBs have:

1. **Displacement** — The move leaving the OB must be impulsive (body > 2x ATR, consecutive large candles)
2. **Fair Value Gap** — The displacement should create an FVG, proving the move was truly imbalanced
3. **Structure break** — The displacement should break market structure (BOS or CHoCH)
4. **Unmitigated** — The OB has not yet been revisited (price hasn't returned to it)

### How OBs Are Used

1. Identify the OB zone from the displacement candle lookback
2. Wait for price to **retrace back** to the OB zone
3. Enter at the OB with a stop loss beyond the OB's opposite extreme
4. Target the next liquidity pool in the displacement direction

### OB Priority (Strongest to Weakest)

1. OB that caused a CHoCH (reversal) + swept liquidity beforehand
2. OB that caused a BOS (continuation) after a pullback
3. OB at the OTE zone (61.8-79% fib retracement)
4. OB overlapping with an unfilled FVG
5. Standalone OB without additional confluence

### OB Invalidation

An OB is **mitigated (invalidated)** when:
- Price returns to the OB zone and trades through it completely
- The body of a candle closes beyond the OB (not just a wick)
- The displacement direction is violated (structure breaks against it)

### Detection Rule

```
For each candle[i] where body > ATR_MULT * ATR (displacement):
  If bullish displacement (close > open):
    Search backwards for last bearish candle → that's the Bullish OB
  If bearish displacement (close < open):
    Search backwards for last bullish candle → that's the Bearish OB
```

---

## 6. Fair Value Gaps (FVG)

Fair Value Gaps are three-candle patterns that reveal price inefficiency — areas where the market moved so fast that it left an "imbalance" that price is likely to revisit.

### Definition

A FVG is a gap between the wicks of candle 1 and candle 3 in a three-candle sequence:

**Bullish FVG (BISI — Buy-Side Imbalance, Sell-Side Inefficiency)**
- Candle 3's low is **higher than** candle 1's high
- The gap between candle 1 high and candle 3 low is the FVG zone
- Indicates buyers overwhelmed sellers so aggressively that a gap formed
- Price is expected to retrace INTO this gap (fill it) before continuing up

**Bearish FVG (SIBI — Sell-Side Imbalance, Buy-Side Inefficiency)**
- Candle 3's high is **lower than** candle 1's low
- The gap between candle 1 low and candle 3 high is the FVG zone
- Indicates sellers overwhelmed buyers
- Price is expected to retrace INTO this gap before continuing down

### FVG as Entry Zones

Traders use FVGs as high-probability entry points:
1. Identify an unfilled FVG in the direction of your bias
2. Wait for price to retrace into the FVG
3. The **midpoint** (50% of the gap, called "consequent encroachment" or CE) is the highest-probability reaction point within the FVG
4. Enter at the FVG with stop beyond the full gap

### FVG Fill Status

- **Unfilled**: Price has not returned to the FVG zone — it remains a valid target
- **Partially filled**: Price entered the FVG but didn't trade through the midpoint
- **Fully filled (mitigated)**: Price traded completely through the FVG — it's no longer valid

### Inverse FVG

When an FVG is fully filled and price continues through it, the FVG "inverts" — it can now act as support/resistance from the opposite direction.

### Detection Rule

```
Bullish FVG: candle[i+2].low > candle[i].high → gap = (candle[i].high, candle[i+2].low)
Bearish FVG: candle[i+2].high < candle[i].low → gap = (candle[i+2].high, candle[i].low)
```

---

## 7. Displacement

Displacement is the hallmark of institutional entry. It's the "fingerprint" that smart money leaves on the chart.

### Definition

A displacement is one or more consecutive candles with:
- **Large bodies** (body > 2x ATR) — institutions aren't subtle
- **Small or no wicks** — the move was aggressive and sustained
- **A clear direction** — either all bullish or all bearish
- **Volume confirmation** (optional) — higher than average volume

### Why Displacement Matters

Displacement proves that institutions aggressively entered the market. Without displacement:
- An OB is just a random candle
- An FVG might be noise
- A structure break might be a false breakout

**No displacement = no trade.** This is one of ICT's hardest rules.

### What Displacement Creates

When displacement occurs, it typically leaves behind:
1. A **Fair Value Gap** (the imbalance from the aggressive move)
2. An **Order Block** (the last opposing candle before the displacement)
3. A **Break of Structure** (the displacement breaks a swing point)
4. A **Liquidity void** (an area where very few orders were filled)

These four elements together form the core of an ICT setup.

### Measuring Displacement

| Strength | Body Size | Consecutive | Quality |
|----------|-----------|-------------|---------|
| Weak | 1.5-2x ATR | Single candle | Low confidence |
| Moderate | 2-3x ATR | 1-2 candles | Standard setup |
| Strong | 3-5x ATR | 2-3 candles | High confidence |
| Extreme | 5x+ ATR | 3+ candles | Highest confidence (but may be exhaustion) |

### Detection Rule

```
Displacement: candle_body > DISPLACEMENT_ATR_MULT * ATR(14)
Consecutive: count adjacent candles in same direction also meeting threshold
```

---

## 8. Premium & Discount Zones

The premium/discount framework tells you whether the current price is "expensive" or "cheap" relative to the recent range.

### Concept

Take any significant swing range (swing low to swing high):
- The **50% level** is **equilibrium** — fair value
- Above 50% is the **premium zone** — price is expensive
- Below 50% is the **discount zone** — price is cheap

### Trading Rules

| Bias | Zone to Enter | Logic |
|------|--------------|-------|
| Bullish | Discount (below 50%) | Buy cheap, sell expensive |
| Bearish | Premium (above 50%) | Sell expensive, buy cheap |
| Any | Equilibrium (50%) | No edge — wait for price to move to a zone |

**Never buy in premium. Never sell in discount.** This is a hard filter.

### PD Arrays

The "arrays" are the collection of all ICT price points (OBs, FVGs, liquidity levels) that fall within the premium or discount zones. For a bullish trade, you want your entry OB/FVG to be in the discount array. For bearish, in the premium array.

### Fibonacci Levels in PD Zones

| Fib Level | Zone | Description |
|-----------|------|-------------|
| 0.0 | Swing extremity | Start of range |
| 0.236 | Deep discount/premium | Extreme value |
| 0.382 | Discount/premium | Good value |
| 0.5 | Equilibrium | Fair value — no edge |
| 0.618 | OTE boundary | Start of OTE zone |
| 0.705 | OTE sweet spot | Highest probability |
| 0.79 | OTE boundary | End of OTE zone |
| 1.0 | Swing extremity | End of range |

---

## 9. Optimal Trade Entry (OTE)

The OTE is ICT's precision entry tool. It pinpoints the highest-probability zone for entering a trade on a retracement.

### Definition

After a significant price swing, the OTE zone is the **61.8% to 79% Fibonacci retracement** of that swing. The **70.5% level** is the "sweet spot" — the single highest-probability entry point.

### How to Calculate

**For a bullish OTE** (buying a pullback in an uptrend):
1. Identify the swing low (start of the move)
2. Identify the swing high (end of the move)
3. Draw Fibonacci from swing low to swing high
4. OTE zone = 61.8% to 79% retracement (measured from the high, going down)

```
Range = swing_high - swing_low
OTE_high = swing_high - (range * 0.618)  ← top of OTE
OTE_low  = swing_high - (range * 0.79)   ← bottom of OTE
Sweet_spot = swing_high - (range * 0.705) ← optimal entry
```

**For a bearish OTE** (selling a pullback in a downtrend):
1. Same process but inverted — measure from swing high to swing low
2. OTE zone = 61.8% to 79% retracement (measured from the low, going up)

### OTE + OB Confluence

The most powerful entry occurs when:
- An **Order Block** sits inside the OTE zone
- An **FVG** overlaps with the OB
- Price pulls back into all three simultaneously

This triple confluence is the gold standard of ICT entries.

### Key Rules

- If price retraces past 79% (beyond the OTE), the setup is weakened
- If price fails to reach 61.8%, it may be too strong to pull back (don't chase)
- The OTE is only valid after displacement — no displacement, no OTE

---

## 10. Kill Zones & Sessions

ICT emphasizes that **when** you trade is as important as **what** you trade. Not all hours are equal.

### Kill Zone Schedule

| Kill Zone | Time (ET) | Time (UTC) | Characteristics |
|-----------|-----------|-----------|----------------|
| **Asian** | 7:00 PM - 10:00 PM | 00:00 - 03:00 | Sets the day's initial range. Low volatility. Consolidation. |
| **London** | 2:00 AM - 5:00 AM | 07:00 - 10:00 | Often establishes the day's high or low. High volatility. Structure breaks. |
| **New York** | 7:00 AM - 10:00 AM | 12:00 - 15:00 | Maximum liquidity (London/NY overlap at open). Trend continuation or reversal. |
| **London Close** | 10:00 AM - 12:00 PM | 15:00 - 17:00 | Profit taking, potential reversals. Secondary kill zone. |

*Times shift by 1 hour during Daylight Saving Time (EDT vs EST).*

### Why Kill Zones Matter

Institutional traders execute during these windows because:
- Maximum liquidity is available to fill large orders
- Volatility creates the displacement moves that form OBs and FVGs
- Economic news releases cluster around these times
- Session opens create predictable patterns (Power of Three)

### Kill Zone Rules

1. **Only enter trades during kill zones** — entries outside kill zones have lower probability
2. **London sets the direction** — the London kill zone often creates the day's high or low
3. **NY confirms or reverses** — the New York session either continues London's move or reverses it
4. **Asian range is context** — use the Asian range to identify consolidation boundaries for London to break

### Crypto Exception

Cryptocurrency markets trade 24/7. Kill zones are less critical for crypto because:
- There's no "session open" with concentrated institutional flow
- Liquidity is more evenly distributed
- However, the 8-10 AM ET window still shows elevated activity (US traders waking up)

This system makes kill zones **optional** for crypto tickers.

### Session-Specific Strategies

| Session | Strategy | What to Look For | What to Avoid |
|---------|----------|-----------------|---------------|
| Asian | Range identification | Consolidation boundaries, daily H/L formation | Trend following, large positions |
| London | Directional bias | Liquidity sweeps, BOS/CHoCH, displacement | Counter-trend trades |
| New York | Momentum/continuation | London follow-through, kill zone entries, OTE pullbacks | Late entries, FOMO |
| London Close | Profit taking | Reversal signals, position management | New entries (except scalps) |

---

## 11. Power of Three

The Power of Three (PO3) describes how every significant move unfolds in three phases. It applies to every timeframe — from 1-minute candles to weekly moves.

### The Three Phases

**Phase 1: Accumulation**
- Price consolidates in a range
- Smart money quietly builds positions
- Volume is typically lower than average
- Retail traders see "nothing happening" and lose interest
- This forms the Asian range on an intraday basis

**Phase 2: Manipulation**
- Price is pushed **against** the intended direction
- This sweep takes out stop losses above/below the range
- Retail traders get trapped (shorts squeeze above, longs stopped below)
- Smart money fills the remainder of their order using the triggered stops as liquidity
- This is the "Judas Swing" — the deceptive move

**Phase 3: Distribution**
- The true directional move begins
- Smart money distributes positions to retail traders entering late
- Displacement creates OBs and FVGs
- Price targets the opposite liquidity pool

### PO3 on a Daily Candle

Every daily candle tells this story:
- **Open** → Accumulation (price near open, building the candle body)
- **High or Low** (whichever comes first) → Manipulation (the wick that grabs liquidity)
- **Close** → Distribution (the final direction of the candle)

For a bullish daily candle:
1. Open → price dips (manipulation, creates the lower wick)
2. Reversal → price rallies through the open (distribution)
3. Close → near the high (the true move)

### PO3 Intraday

On an intraday basis:
1. Asian session = Accumulation (price ranges)
2. London open = Manipulation (sweep one side of Asian range)
3. NY session = Distribution (true move in the opposite direction)

---

## 12. Breaker Blocks

Breaker Blocks are an advanced concept that identifies strong reaction points from failed market swings.

### Definition

A **Breaker Block** forms when:
1. Price runs liquidity (takes out a swing high or low)
2. Then **aggressively reverses**, breaking market structure
3. The candle(s) at the swing point that was violated become the Breaker Block

### Types

**Bullish Breaker Block:**
1. Price sweeps sell-side liquidity (takes out a swing low)
2. Immediately reverses with displacement
3. Breaks above the previous swing high (CHoCH)
4. The candle(s) of the swing low that was swept = Bullish Breaker

**Bearish Breaker Block:**
1. Price sweeps buy-side liquidity (takes out a swing high)
2. Immediately reverses with displacement
3. Breaks below the previous swing low (CHoCH)
4. The candle(s) of the swing high that was swept = Bearish Breaker

### Why Breakers Work

The Breaker represents a zone where:
- Trapped traders (who bought the breakout) will have stops
- Smart money absorbed their orders during the sweep
- When price returns to this zone, it's expected to react strongly

### How to Trade Breakers

1. Identify the sweep + reversal pattern
2. Mark the Breaker Block zone
3. Wait for price to retrace to the Breaker
4. Enter with a stop beyond the Breaker zone
5. Target the next liquidity pool

---

## 13. Mitigation Blocks

Mitigation Blocks are similar to Breaker Blocks but form from **failed swings** rather than swept swings.

### Definition

A **Mitigation Block** forms when:
1. Price makes a swing but **fails to run liquidity** (doesn't take out the previous high/low)
2. Then aggressively reverses and breaks structure
3. The candle(s) at the failed swing point become the Mitigation Block

### Difference from Breakers

| Feature | Breaker Block | Mitigation Block |
|---------|--------------|-----------------|
| Liquidity | Swept (ran the level) | Not swept (failed to reach) |
| Pattern | Sweep + reversal | Failed swing + reversal |
| Strength | Stronger (liquidity was grabbed) | Moderate (smart money needs to revisit) |
| Purpose | Smart money trapped retail here | Smart money has unfilled orders here |

### Why Mitigation Blocks Work

The theory is that institutions had orders at the failed swing point that didn't get fully filled. When price returns to mitigate (balance) those unfilled orders, it reacts.

---

## 14. Silver Bullet Strategy

The Silver Bullet is ICT's signature high-probability, time-specific setup.

### Time Windows

| Silver Bullet Window | Time (ET) | Context |
|---------------------|-----------|---------|
| AM Silver Bullet | 10:00 - 11:00 AM | After NY open volatility settles |
| PM Silver Bullet | 3:00 - 4:00 PM | Before market close, final positioning |

### Setup Requirements

1. **Clear daily bias** established from HTF analysis
2. **Market structure** confirmed on the entry timeframe
3. **Liquidity sweep** occurred (manipulation phase complete)
4. **FVG forms** during the Silver Bullet window
5. Price retraces into the FVG for entry
6. Target the **opposite liquidity pool**

### Why These Time Windows

- 10:00-11:00 AM: The initial NY open volatility has created the manipulation move. Smart money now needs to execute the distribution phase.
- 3:00-4:00 PM: End-of-day positioning. Institutions adjust positions before close, creating a final burst of directional movement.

---

## 15. Judas Swing

The Judas Swing is the manipulation phase of the Power of Three, given its own name because of its deceptive nature.

### Definition

A **Judas Swing** is a false move that:
1. Occurs at the beginning of a session (typically London or NY open)
2. Moves **against** the true intended direction
3. Sweeps liquidity on one side of the range
4. Creates the illusion of a breakout, trapping retail traders
5. Then reverses sharply in the true direction

### How to Identify

1. Note the Asian range (or previous session range)
2. At session open, price moves to one extreme of the range
3. It **breaks** beyond the range boundary (triggering stops)
4. But then immediately reverses with displacement
5. The Judas Swing high/low becomes the session high/low

### Trading the Judas Swing

1. Wait for the initial move at session open
2. If it sweeps liquidity (runs stops) with a wick, that's the Judas Swing
3. Wait for displacement in the opposite direction
4. Enter on the pullback to the FVG/OB created by the displacement
5. Target the opposite side of the range + beyond

---

## 16. Unicorn Model

The Unicorn Model is a specific confluence pattern that combines multiple ICT concepts into a single, high-probability setup.

### Requirements (All Must Be Present)

1. **CHoCH (Change of Character)** — market structure shifts direction
2. **Breaker Block** — formed from the liquidity sweep that caused the CHoCH
3. **FVG** — created by the displacement that broke structure
4. **FVG + Breaker overlap** — the FVG must overlap with the Breaker Block zone

### Why It's Called "Unicorn"

Because all four elements aligning simultaneously is rare — but when it happens, the probability of a successful trade is exceptionally high.

### Execution

1. Identify the CHoCH (structure break against the prior trend)
2. Mark the Breaker Block at the swept swing point
3. Mark the FVG created by the displacement
4. If the FVG overlaps with the Breaker, you have a Unicorn setup
5. Enter when price retraces to the overlap zone
6. Stop beyond the Breaker Block
7. Target the next liquidity pool

---

## 17. Multi-Timeframe Analysis

ICT uses a top-down approach. Higher timeframes set the bias; lower timeframes provide the entry.

### The Three Levels

| Level | Timeframe | Purpose | What to Look For |
|-------|-----------|---------|-----------------|
| **Bias** | Weekly / Daily | Determine trend direction | Swing structure, BOS/CHoCH, major OBs |
| **Setup** | 4H / 1H | Identify the trade setup | FVGs, OBs, displacement, liquidity zones |
| **Entry** | 15M / 5M | Time the precise entry | OTE zone, kill zone timing, FVG entry |

### Rules for Multi-Timeframe Alignment

1. **Higher timeframe overrides lower timeframe** — if daily is bearish, ignore bullish signals on 15M
2. **Don't skip levels** — always check bias before looking for setups
3. **HTF provides the "where"** — daily OBs and FVGs are stronger zones
4. **LTF provides the "when"** — 15M entries within 1H OBs give precision
5. **Structure breaks cascade** — a daily CHoCH will show as multiple 1H CHoCHs

### Example Workflow

1. **Daily**: Bearish structure (lower highs, lower lows). Bias = SHORT only.
2. **1H**: Price pulling back to a bearish OB that overlaps with a bearish FVG. Displacement occurred on the move down.
3. **15M**: Price enters the OTE zone (61.8-79% retracement). An FVG forms on the 15M within the 1H OB. Kill zone active (NY open). Enter short.

---

## 18. Risk Management

ICT risk management is conservative and position-size based.

### Core Rules

| Rule | Value | Reasoning |
|------|-------|-----------|
| Max risk per trade | 1-2% of account | Survive losing streaks |
| Minimum R:R | 2:1 | Profitable even at 40% win rate |
| Max concurrent positions | 3 | Cap total risk at 3-6% |
| Stop loss placement | Beyond the OB | Let the OB "protect" your stop |
| Drawdown circuit breaker | 10% from peak | Force a pause and review |

### Position Sizing Formula

```
Risk Amount = Account Balance * Risk % (e.g., 1%)
Position Size = Risk Amount / |Entry Price - Stop Loss|
```

Example:
- Account: $100,000
- Risk: 1% = $1,000
- Entry: $250.00
- Stop Loss: $248.00
- Risk per share: $2.00
- Position Size: $1,000 / $2.00 = 500 shares

### Stop Loss Placement

ICT stops are placed **beyond the Order Block**:

- Long entry at bullish OB: Stop below the OB low
- Short entry at bearish OB: Stop above the OB high
- Add a small buffer (a few ticks) beyond the OB extreme

**Never use arbitrary stops** (like "50 pips" or "2%"). Stops must be at structural levels.

### Take Profit Targets

| Target | Level | When to Use |
|--------|-------|------------|
| TP1 | Next swing high/low | Conservative — secure partial profits |
| TP2 | Opposite liquidity pool | Standard — full ICT target |
| TP3 | HTF OB or FVG | Aggressive — for strong trends |

### Trade Management

1. At TP1: Move stop to breakeven
2. At TP2: Close 50% of position, trail stop
3. If invalidation occurs (price closes beyond OB): Exit immediately, don't wait for SL

---

## 19. Complete Trade Execution Framework

### Pre-Trade Checklist (All Must Be Yes)

- [ ] HTF bias determined? (Daily structure = bullish or bearish)
- [ ] Currently in a kill zone? (London, NY, or Asian — skip for crypto)
- [ ] Displacement occurred? (Impulsive candle > 2x ATR)
- [ ] FVG + OB confluence identified? (They overlap in price)
- [ ] OTE zone calculated? (Entry in 61.8-79% retracement)
- [ ] Liquidity swept? (Stops were taken before the setup)
- [ ] Premium/discount aligned? (Buying in discount, selling in premium)
- [ ] R:R >= 2:1? (Reward at least 2x the risk)
- [ ] Risk <= 1-2% of account? (Position sized correctly)

If ANY box is unchecked, **NO TRADE**.

### Step-by-Step Execution

**1. Pre-Market (Before Session Opens)**
- Analyze daily chart for bias (swing structure, BOS/CHoCH)
- Mark major liquidity levels (previous day high/low, swing points)
- Identify daily OBs and FVGs as areas of interest
- Note the Asian range boundaries

**2. Kill Zone Opens (London or NY)**
- Watch for the Judas Swing (manipulation move)
- Wait for liquidity to be swept (stops taken)
- Look for displacement (impulsive reversal candle)
- Mark the OB and FVG created by the displacement

**3. Entry Setup**
- Draw Fibonacci from the displacement swing
- Wait for price to retrace into the OTE zone (61.8-79%)
- Confirm price is in correct zone (discount for longs, premium for shorts)
- Verify OTE overlaps with OB and/or FVG (confluence)

**4. Execute**
- Enter at the OTE sweet spot (70.5%) or at the FVG/OB level
- Stop loss beyond the OB
- TP1 at the recent swing high/low
- TP2 at the opposite liquidity pool

**5. Manage**
- Move stop to breakeven at TP1
- Trail or close at TP2
- Exit immediately if invalidation occurs

---

## 20. Algorithmic Detection Rules

These are the exact rules used by this paper trading system to detect ICT concepts programmatically from OHLC candle data.

### ATR (Average True Range)

```
True Range = max(high - low, |high - prev_close|, |low - prev_close|)
ATR = rolling_mean(True Range, period=14)
```

### Swing Detection

```python
# Swing High: bar's high exceeds all bars within lookback on both sides
for i in range(lookback, len(candles) - lookback):
    if candle[i].high > max(candle[i-lookback:i].high) and
       candle[i].high > max(candle[i+1:i+lookback+1].high):
        → swing_high at candle[i]

# Swing Low: bar's low is less than all bars within lookback
    if candle[i].low < min(candle[i-lookback:i].low) and
       candle[i].low < min(candle[i+1:i+lookback+1].low):
        → swing_low at candle[i]
```

### Fair Value Gap

```python
# Bullish FVG
if candle[i+2].low > candle[i].high:
    fvg = {top: candle[i+2].low, bottom: candle[i].high}

# Bearish FVG
if candle[i+2].high < candle[i].low:
    fvg = {top: candle[i].low, bottom: candle[i+2].high}
```

### Displacement

```python
if candle_body(candle[i]) > ATR_MULT * ATR[i]:
    → displacement detected
    direction = "bullish" if close > open else "bearish"
```

### Order Block

```python
# After detecting displacement at candle[i]:
for j in range(i-1, i-lookback-1, -1):
    if displacement is bullish AND candle[j] is bearish:
        → Bullish OB at candle[j] (range: j.low to j.high)
        break
    if displacement is bearish AND candle[j] is bullish:
        → Bearish OB at candle[j]
        break
```

### Liquidity Zones

```python
# Cluster swing highs/lows within tolerance (0.2%)
for each pair of swing points:
    if abs(level_a - level_b) / level_a <= 0.002:
        → cluster them into a single liquidity zone
        touch_count = number of swings in cluster
```

### Liquidity Sweep

```python
# Buy-side sweep
if candle.high > zone.level AND candle.close < zone.level:
    → swept (wick through, close back below)

# Sell-side sweep
if candle.low < zone.level AND candle.close > zone.level:
    → swept
```

### OTE Zone

```python
range = swing_high - swing_low

# Bullish OTE (for buying pullbacks in uptrend)
ote_high = swing_high - range * 0.618
ote_low  = swing_high - range * 0.79
sweet_spot = swing_high - range * 0.705
```

### Confluence Score

```
+20 pts: HTF bias aligns with entry direction
+15 pts: Unfilled FVG present in direction
+15 pts: Unmitigated OB present in direction
+15 pts: FVG overlaps with OB
+10 pts: Price is in OTE zone
+10 pts: Displacement occurred
+10 pts: Liquidity was swept
+ 5 pts: Inside a kill zone (or crypto)
+ 5 pts: Premium/discount aligns with bias
────────
100 pts maximum
 60 pts minimum to consider a trade
```

---

## 21. Glossary

| Term | Definition |
|------|-----------|
| **ATR** | Average True Range — measure of volatility over N periods |
| **BOS** | Break of Structure — price breaks a swing point in the trend direction (continuation) |
| **BSL** | Buy-Side Liquidity — stop orders above swing highs |
| **Breaker Block** | Failed OB after a liquidity sweep + reversal |
| **CE** | Consequent Encroachment — the 50% (midpoint) of an FVG |
| **CHoCH** | Change of Character — price breaks a swing point against the trend (reversal) |
| **Displacement** | Large impulsive candle (body > 2x ATR) indicating institutional entry |
| **EQ** | Equilibrium — the 50% level of a range |
| **FVG** | Fair Value Gap — three-candle imbalance pattern |
| **HH** | Higher High — swing high above previous swing high (bullish) |
| **HL** | Higher Low — swing low above previous swing low (bullish) |
| **ICT** | Inner Circle Trader — methodology by Michael J. Huddleston |
| **Inducement** | False move designed to trigger retail stops and create liquidity |
| **Judas Swing** | The manipulation move at session open (false direction) |
| **Kill Zone** | Specific time windows of peak institutional activity |
| **LH** | Lower High — swing high below previous swing high (bearish) |
| **LL** | Lower Low — swing low below previous swing low (bearish) |
| **Liquidity** | Clusters of orders at predictable levels that smart money targets |
| **Mean Threshold** | The 50% level of an OB — highest probability reaction point |
| **Mitigation** | When price returns to and trades through an OB or FVG |
| **Mitigation Block** | Failed swing point where institutions have unfilled orders |
| **MSS** | Market Structure Shift — same as CHoCH |
| **OB** | Order Block — last opposing candle before displacement |
| **OTE** | Optimal Trade Entry — 61.8-79% Fibonacci retracement zone |
| **PD Array** | Premium & Discount Array — collection of ICT levels in P/D zones |
| **PO3** | Power of Three — Accumulation, Manipulation, Distribution |
| **Silver Bullet** | Time-specific setup at 10-11am or 3-4pm ET |
| **Smart Money** | Institutional traders (banks, hedge funds, market makers) |
| **SMC** | Smart Money Concepts — broader term for ICT-style analysis |
| **SSL** | Sell-Side Liquidity — stop orders below swing lows |
| **Sweep** | Price moves through a liquidity level then reverses (stop hunt) |
| **Unicorn Model** | CHoCH + Breaker Block + FVG overlap = highest probability setup |

---

*This documentation is for educational purposes within the ICT Paper Trading Simulator. It synthesizes publicly available ICT concepts for algorithmic implementation. It is not financial advice and not affiliated with Michael J. Huddleston or his programs.*
