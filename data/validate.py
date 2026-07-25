"""Check a Databento dataset before trusting it in a backtest.

Reports what the file contains, whether its session calendar matches CME, and
whether anything is missing. Classification is rule-based rather than a hardcoded
holiday table, so it keeps working on the next download.
"""

from __future__ import annotations

import json
import os

import pandas as pd

from data.historical import (
    front_month_schedule,
    load_continuous_contract,
    session_day,
    _read_dbn,
    load_csv,
)

_ET = "America/New_York"

# Bars in a full CME equity-index session, by weekday of the session day.
# Mon-Thu run 23 hours (the 17:00 ET hour is the maintenance halt), Friday has
# no evening session, and Sunday only has one.
FULL_SESSION_BARS = {0: 1380, 1: 1380, 2: 1380, 3: 1380, 4: 1020, 6: 360}

SHORT_DAY_TOLERANCE = 120  # bars a session may lack before it is called short


def _load_raw(filepath: str) -> pd.DataFrame:
    """Read per-contract bars, spreads already dropped."""
    if ".dbn" in filepath:
        return _read_dbn(filepath)
    return load_csv(filepath)


def _classify_short_day(row, volume_median: float) -> str:
    """Say why a session day has fewer bars than a full session."""
    if row["last_et"].hour < 16:
        return "early close"
    if row["first_et"].hour >= 19:
        return "late open (missing evening session)"
    if row["volume"] < volume_median * 0.25:
        return "holiday (thin)"
    return "UNEXPLAINED"


def _classify_gap(before: pd.Timestamp, after: pd.Timestamp) -> str:
    """Say why there are no bars between two consecutive timestamps."""
    hours = (after - before).total_seconds() / 3600
    if hours <= 1.02:
        return "daily maintenance halt"
    if before.weekday() == 4 and after.weekday() == 6:
        return "weekend"
    if before.weekday() == 4:
        return "weekend plus holiday"
    if hours <= 26:
        return "holiday"
    return "extended holiday"


def validate(filepath: str) -> dict:
    """Validate a dataset and print a report.

    Returns a dict of findings. `findings["problems"]` is empty when everything
    the checker knows how to explain is explained.
    """
    problems: list[str] = []
    print(f"\n  Dataset: {filepath}")

    raw = _load_raw(filepath)
    front = load_continuous_contract(filepath)

    # --- contents -----------------------------------------------------------
    print("\n  --- Contents ---")
    print(f"  Records (outright):   {len(raw):,}")
    print(f"  Front-month bars:     {len(front):,}")
    print(f"  Contracts:            {raw['symbol'].nunique() if 'symbol' in raw else 1}")
    print(f"  Range:                {front['timestamp'].min()} to {front['timestamp'].max()}")

    if "symbol" in raw.columns:
        spreads = int(raw["symbol"].str.contains("-", na=False).sum())
        print(f"  Calendar spreads left: {spreads}")
        if spreads:
            problems.append(f"{spreads} calendar-spread records survived the filter")

    # --- integrity ----------------------------------------------------------
    print("\n  --- Integrity ---")
    checks = {
        "high below low": int((raw["high"] < raw["low"]).sum()),
        "open outside range": int(((raw["open"] > raw["high"]) | (raw["open"] < raw["low"])).sum()),
        "close outside range": int(((raw["close"] > raw["high"]) | (raw["close"] < raw["low"])).sum()),
        "volume not positive": int((raw["volume"] <= 0).sum()),
        "null values": int(raw.isna().sum().sum()),
        "duplicate front-month timestamps": int(front["timestamp"].duplicated().sum()),
    }
    for name, count in checks.items():
        print(f"  {name:34} {count}")
        if count:
            problems.append(f"{count} records with {name}")

    # --- session calendar ---------------------------------------------------
    et = front["timestamp"].dt.tz_convert(_ET)
    saturdays = int((et.dt.weekday == 5).sum())
    halt = front[et.dt.hour == 17]

    print("\n  --- Session calendar ---")
    print(f"  Saturday bars:        {saturdays}")
    if saturdays:
        problems.append(f"{saturdays} bars on a Saturday, when ES does not trade")

    print(f"  Bars in 17:00 ET halt hour: {len(halt)}")
    for _, bar in halt.iterrows():
        flat = bar["high"] == bar["low"]
        print(f"     {bar['timestamp'].tz_convert(_ET)}  close={bar['close']}  "
              f"volume={bar['volume']}  {'flat' if flat else 'NOT FLAT'}")
        if not flat:
            problems.append(f"non-flat bar inside the maintenance halt at {bar['timestamp']}")

    # --- short sessions -----------------------------------------------------
    days = front.assign(sd=session_day(front["timestamp"]), et=et).groupby("sd").agg(
        bars=("close", "size"), volume=("volume", "sum"),
        first_et=("et", "min"), last_et=("et", "max"),
    ).reset_index()
    days["expected"] = pd.to_datetime(days["sd"]).dt.weekday.map(FULL_SESSION_BARS)
    days = days.dropna(subset=["expected"])
    days["missing"] = days["expected"] - days["bars"]

    volume_median = days["volume"].median()
    short = days[days["missing"] > SHORT_DAY_TOLERANCE].copy()
    short["why"] = short.apply(lambda r: _classify_short_day(r, volume_median), axis=1)

    print(f"\n  --- Short sessions ({len(short)} of {len(days)} days) ---")
    for why, group in short.groupby("why"):
        print(f"  {why}: {len(group)}")
    unexplained = short[short["why"] == "UNEXPLAINED"]
    for _, row in unexplained.iterrows():
        print(f"     {row['sd'].date()} {row['sd'].strftime('%a')}  "
              f"{int(row['bars'])}/{int(row['expected'])} bars  "
              f"{row['first_et'].strftime('%H:%M')}-{row['last_et'].strftime('%H:%M')} ET")
        problems.append(f"unexplained short session on {row['sd'].date()}")

    # --- gaps ---------------------------------------------------------------
    gap_hours = front["timestamp"].diff().dt.total_seconds() / 3600
    gaps = gap_hours[gap_hours > 1.02]
    labels = [
        _classify_gap(front["timestamp"].iloc[i - 1], front["timestamp"].iloc[i])
        for i in gaps.index
    ]
    print(f"\n  --- Gaps over one hour ({len(gaps)}) ---")
    for label, count in pd.Series(labels).value_counts().items():
        print(f"  {label}: {count}")

    # --- session reopens ----------------------------------------------------
    reopen = int((gap_hours > 1.02).sum())
    print(f"\n  --- Session reopens ---")
    print(f"  Bars opening after a break: {reopen}")
    print("  These are real gaps, but the FVG and displacement detectors read")
    print("  each one as a signal. Backtests report how many signals land here.")

    # --- rolls --------------------------------------------------------------
    if "symbol" in raw.columns and raw["symbol"].nunique() > 1:
        schedule = front_month_schedule(raw.assign(session_day=session_day(raw["timestamp"])))
        changes = schedule[schedule != schedule.shift()]
        print(f"\n  --- Rolls ({len(changes)} front-month contracts) ---")
        for day, sym in changes.items():
            print(f"     {day.date()}  {sym}")

        roll_days = set(changes.index[1:])
        step = front["close"].diff().abs()
        on_roll = step[front.assign(sd=session_day(front["timestamp"]))["sd"].isin(roll_days)]
        if len(on_roll):
            worst = on_roll.max()
            typical = step.quantile(0.9999)
            print(f"  Largest price step on a roll day: {worst:.2f} points "
                  f"(series 99.99th percentile is {typical:.2f})")
            if worst > typical * 2:
                problems.append(
                    f"roll day price step of {worst:.2f} points suggests back-adjustment failed"
                )

    # --- condition.json -----------------------------------------------------
    condition_path = os.path.join(os.path.dirname(filepath), "condition.json")
    if os.path.exists(condition_path):
        with open(condition_path) as handle:
            entries = json.load(handle)
        by_day = days.set_index(days["sd"].dt.date)["missing"].to_dict()
        flagged = [e for e in entries if e["condition"] != "available"]

        print(f"\n  --- Data condition ({len(entries)} days listed) ---")
        material, benign = [], []
        for entry in flagged:
            date = pd.Timestamp(entry["date"]).date()
            if pd.Timestamp(entry["date"]).weekday() == 5:
                continue  # Saturdays carry no data by design
            short_by = by_day.get(date)
            if short_by is not None and short_by > SHORT_DAY_TOLERANCE:
                material.append((entry, short_by))
            else:
                benign.append(entry)
        print(f"  Flagged but complete: {len(benign)}")
        print(f"  Flagged and short:    {len(material)}")
        for entry, short_by in material:
            print(f"     {entry['date']} {entry['condition']}: {int(short_by)} bars missing")
            problems.append(f"{entry['date']} is {entry['condition']} and short {int(short_by)} bars")

    # --- verdict ------------------------------------------------------------
    print("\n  --- Verdict ---")
    if problems:
        print(f"  {len(problems)} issue(s) need a decision:")
        for problem in problems:
            print(f"     {problem}")
    else:
        print("  Everything the checker can explain is explained.")
    print()

    return {"problems": problems, "front_bars": len(front), "days": len(days)}
