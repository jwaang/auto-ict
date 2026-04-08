"""Kill Zone and Silver Bullet session time windows.

Kill Zones:
  London: 2:00 - 5:00 AM ET
  New York: 7:00 - 10:00 AM ET
  Asian: 7:00 - 10:00 PM ET

Silver Bullet Windows (narrow 1-hour execution windows):
  London: 3:00 - 4:00 AM ET
  NY AM: 10:00 - 11:00 AM ET (highest probability)
  NY PM: 2:00 - 3:00 PM ET

London Close: 10:00 AM - 12:00 PM ET (retracement window)
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from config import KILL_ZONES_ET, SILVER_BULLET_WINDOWS, LONDON_CLOSE_KZ

ET = ZoneInfo("America/New_York")


def get_active_killzone(ts: datetime) -> str | None:
    """Return the active kill zone name, or None if outside all kill zones.

    Args:
        ts: Timezone-aware datetime (will be converted to ET)
    """
    et_time = ts.astimezone(ET)
    hour = et_time.hour

    for name, (start, end) in KILL_ZONES_ET.items():
        if start <= hour < end:
            return name
    return None


def get_silver_bullet_window(ts: datetime) -> str | None:
    """Return the active Silver Bullet window name, or None.

    Silver Bullet windows are narrow 1-hour windows where FVGs form
    with high reliability. Entries during these windows in alignment
    with HTF bias are highest probability.
    """
    if ts is None:
        return None
    et_time = ts.astimezone(ET)
    hour = et_time.hour

    for name, (start, end) in SILVER_BULLET_WINDOWS.items():
        if start <= hour < end:
            return name
    return None


def is_in_killzone(ts: datetime) -> bool:
    """Check if timestamp falls within any kill zone."""
    return get_active_killzone(ts) is not None


def is_london_close(ts: datetime) -> bool:
    """Check if timestamp is in London Close kill zone (retracement window)."""
    if ts is None:
        return False
    et_time = ts.astimezone(ET)
    return LONDON_CLOSE_KZ[0] <= et_time.hour < LONDON_CLOSE_KZ[1]


def is_crypto(ticker: str) -> bool:
    """Check if ticker is likely a crypto asset (kill zones optional)."""
    crypto_suffixes = ("-USD", "-USDT", "-BTC", "-ETH", "USDT", "BUSD")
    return any(ticker.upper().endswith(s) for s in crypto_suffixes)
