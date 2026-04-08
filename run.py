"""Automated runner — called by scheduler or cron.

Runs analysis on the configured TICKER, then checks open positions.
Designed to be called headlessly with no user interaction.
"""

import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent))

from config import TICKER
from ict.killzones import is_crypto

ET = ZoneInfo("America/New_York")


def run():
    ticker = TICKER
    now_et = datetime.now(ET)
    print(f"[{now_et.strftime('%Y-%m-%d %H:%M ET')}] Automated ICT analysis: {ticker}")

    # For equities, skip if outside market-relevant hours (5am-5pm ET weekdays)
    if not is_crypto(ticker):
        if now_et.weekday() >= 5:  # Saturday/Sunday
            print(f"  Skipping {ticker} — weekend")
            return
        if now_et.hour < 5 or now_et.hour >= 17:
            print(f"  Skipping {ticker} — outside market hours")
            return

    # Run analysis
    from main import cmd_analyze
    cmd_analyze(ticker)

    # Check open positions
    from main import cmd_check_positions
    cmd_check_positions()


if __name__ == "__main__":
    run()
