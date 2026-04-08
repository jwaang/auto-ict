"""Kill Zone session time windows.

London: 2:00 - 5:00 AM ET
New York: 7:00 - 10:00 AM ET
Asian: 7:00 - 10:00 PM ET
"""

from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

KILL_ZONES = {
    "london": (2, 5),
    "new_york": (7, 10),
    "asian": (19, 22),
}


def get_active_killzone(ts: datetime) -> str | None:
    """Return the active kill zone name, or None if outside all kill zones.

    Args:
        ts: Timezone-aware datetime (will be converted to ET)
    """
    et_time = ts.astimezone(ET)
    hour = et_time.hour

    for name, (start, end) in KILL_ZONES.items():
        if start <= hour < end:
            return name
    return None


def is_in_killzone(ts: datetime) -> bool:
    """Check if timestamp falls within any kill zone."""
    return get_active_killzone(ts) is not None


def is_crypto(ticker: str) -> bool:
    """Check if ticker is likely a crypto asset (kill zones optional)."""
    crypto_suffixes = ("-USD", "-USDT", "-BTC", "-ETH", "USDT", "BUSD")
    return any(ticker.upper().endswith(s) for s in crypto_suffixes)
