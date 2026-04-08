"""Alpaca Markets data client — REST for historical bars, WebSocket for real-time streaming.

Free tier: real-time crypto WebSocket (minute bars, trades, quotes), 200 REST calls/min.
Sign up at https://app.alpaca.markets/signup (no payment required).
"""

import asyncio
import json
import logging
import urllib.request
from datetime import datetime, timezone

import pandas as pd

from config import ALPACA_API_KEY, ALPACA_REST_URL, ALPACA_SECRET_KEY, ALPACA_WS_URL

log = logging.getLogger(__name__)

_HEADERS = {
    "APCA-API-KEY-ID": ALPACA_API_KEY,
    "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
}


# ─── REST API ────────────────────────────────────────────────────────────────

def get_bars(
    symbol: str,
    timeframe: str = "5Min",
    limit: int = 100,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Fetch historical bars from Alpaca REST API.

    Args:
        symbol: Alpaca format e.g. "BTC/USD"
        timeframe: "1Min", "5Min", "15Min", "1Hour", "1Day"
        limit: Max bars to return (max 10000)
        start: RFC-3339 start time (optional)
        end: RFC-3339 end time (optional)

    Returns:
        DataFrame with timestamp, open, high, low, close, volume
    """
    _check_keys()
    encoded_symbol = symbol.replace("/", "%2F")
    url = f"{ALPACA_REST_URL}/bars?symbols={encoded_symbol}&timeframe={timeframe}&limit={limit}"
    if start:
        url += f"&start={start}"
    if end:
        url += f"&end={end}"

    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    bars = data.get("bars", {}).get(symbol, [])
    if not bars:
        raise RuntimeError(f"No bars returned for {symbol} ({timeframe})")

    rows = []
    for bar in bars:
        rows.append({
            "timestamp": datetime.fromisoformat(bar["t"].replace("Z", "+00:00")),
            "open": float(bar["o"]),
            "high": float(bar["h"]),
            "low": float(bar["l"]),
            "close": float(bar["c"]),
            "volume": int(bar.get("v", 0)),
        })

    return pd.DataFrame(rows)


def get_latest_bar(symbol: str) -> dict:
    """Get the most recent bar for a symbol."""
    _check_keys()
    encoded_symbol = symbol.replace("/", "%2F")
    url = f"{ALPACA_REST_URL}/latest/bars?symbols={encoded_symbol}"
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    bar = data.get("bars", {}).get(symbol)
    if not bar:
        raise RuntimeError(f"No latest bar for {symbol}")
    return {
        "timestamp": bar["t"],
        "open": float(bar["o"]),
        "high": float(bar["h"]),
        "low": float(bar["l"]),
        "close": float(bar["c"]),
        "volume": int(bar.get("v", 0)),
    }


# ─── WebSocket Streaming ────────────────────────────────────────────────────

async def stream_bars(
    symbols: list[str],
    on_bar=None,
    on_error=None,
):
    """Stream real-time minute bars via Alpaca WebSocket.

    Args:
        symbols: List of Alpaca-format symbols e.g. ["BTC/USD"]
        on_bar: Callback(symbol: str, bar: dict) called on each minute bar
        on_error: Optional error callback(error: Exception)

    This is a long-running coroutine — it reconnects on disconnect.
    """
    import websockets

    _check_keys()

    while True:
        try:
            async with websockets.connect(ALPACA_WS_URL) as ws:
                # Wait for connection message
                msg = json.loads(await ws.recv())
                log.info(f"WS connected: {msg}")

                # Authenticate
                auth_msg = json.dumps({
                    "action": "auth",
                    "key": ALPACA_API_KEY,
                    "secret": ALPACA_SECRET_KEY,
                })
                await ws.send(auth_msg)
                auth_resp = json.loads(await ws.recv())
                log.info(f"WS auth: {auth_resp}")

                if any(m.get("T") == "error" for m in auth_resp if isinstance(m, dict)):
                    raise RuntimeError(f"WebSocket auth failed: {auth_resp}")

                # Subscribe to minute bars
                sub_msg = json.dumps({
                    "action": "subscribe",
                    "bars": symbols,
                })
                await ws.send(sub_msg)
                sub_resp = json.loads(await ws.recv())
                log.info(f"WS subscribed: {sub_resp}")

                # Process incoming messages
                async for raw in ws:
                    messages = json.loads(raw)
                    for msg in messages:
                        if msg.get("T") == "b":  # Bar message
                            bar = {
                                "timestamp": msg["t"],
                                "open": float(msg["o"]),
                                "high": float(msg["h"]),
                                "low": float(msg["l"]),
                                "close": float(msg["c"]),
                                "volume": int(msg.get("v", 0)),
                            }
                            await on_bar(msg["S"], bar)

        except Exception as e:
            log.error(f"WebSocket error: {e}")
            if on_error:
                on_error(e)
            log.info("Reconnecting in 5 seconds...")
            await asyncio.sleep(5)


def _check_keys():
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        raise RuntimeError(
            "Alpaca API keys not set. Add ALPACA_API_KEY and ALPACA_SECRET_KEY to .env\n"
            "Sign up free at https://app.alpaca.markets/signup"
        )
