"""Configuration constants for ICT Paper Trading Simulator."""

import os
from pathlib import Path

# Project paths
PROJECT_ROOT = Path(__file__).parent
TRADE_LOG_PATH = PROJECT_ROOT / "logs" / "trades.json"

# Default ticker (overridable via CLI/UI)
TICKER = "BTC-USD"

# Multi-timeframe configuration
# bias (daily) → swing (4h) → setup (1h) → entry (15m)
TIMEFRAMES = {
    "bias": {"interval": "1d", "range": "6mo"},
    "swing": {"interval": "1h", "range": "1mo", "aggregate_to": "4h"},
    "setup": {"interval": "1h", "range": "1mo"},
    "entry": {"interval": "15m", "range": "5d"},
}

# Account defaults
STARTING_BALANCE = 100_000.0
RISK_PER_TRADE_PCT = 1.0       # Max 1% of account per trade
MIN_RR_RATIO = 2.0             # Minimum 2:1 reward:risk
MAX_CONCURRENT_POSITIONS = 3   # Max 3 open positions
MAX_DRAWDOWN_PCT = 10.0        # Circuit breaker: pause at 10% drawdown from peak

# ICT detection parameters
ATR_PERIOD = 14
DISPLACEMENT_ATR_MULT = 2.0    # Candle body > 2x ATR = displacement
SWING_LOOKBACK = 5             # Bars each side for swing detection
LIQUIDITY_CLUSTER_TOLERANCE = 0.002  # 0.2% price proximity = cluster

# Fibonacci / OTE
OTE_FIB_LOW = 0.618
OTE_FIB_HIGH = 0.79
OTE_FIB_SWEET_SPOT = 0.705

# Kill Zone times (Eastern Time, 24h format)
KILL_ZONES_ET = {
    "london": (2, 5),      # 2:00 - 5:00 AM ET
    "new_york": (7, 10),   # 7:00 - 10:00 AM ET
    "asian": (19, 22),     # 7:00 - 10:00 PM ET
}

# Confluence scoring weights
CONFLUENCE_WEIGHTS = {
    "htf_bias_aligned": 20,
    "fvg_present": 15,
    "ob_present": 15,
    "fvg_ob_overlap": 15,
    "in_ote_zone": 10,
    "displacement_present": 10,
    "liquidity_sweep": 10,
    "in_kill_zone": 5,
    "premium_discount_aligned": 5,
}
MIN_CONFLUENCE_SCORE = 60  # Minimum score to call Claude API

# Claude API
CLAUDE_MODEL = "claude-sonnet-4-20250514"
CLAUDE_TEMPERATURE = 0.3
CLAUDE_MAX_TOKENS = 2000

def _load_env_var(name: str) -> str:
    """Load a variable from env or local .env file."""
    val = os.environ.get(name, "")
    if val:
        return val
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""

ANTHROPIC_API_KEY = _load_env_var("ANTHROPIC_API_KEY")

# Alpaca Markets (free tier — real-time crypto WebSocket + REST)
ALPACA_API_KEY = _load_env_var("ALPACA_API_KEY")
ALPACA_SECRET_KEY = _load_env_var("ALPACA_SECRET_KEY")
ALPACA_WS_URL = "wss://stream.data.alpaca.markets/v1beta3/crypto/us"
ALPACA_REST_URL = "https://data.alpaca.markets/v1beta3/crypto/us"

# Monitor settings
ANALYSIS_INTERVAL_MINUTES = 30  # How often to run ICT analysis
MONITOR_CHECK_INTERVAL = 60     # Seconds between journal re-reads when no positions

# Risk validation bounds
MIN_SL_DISTANCE_PCT = 0.001   # SL must be at least 0.1% from entry
MAX_SL_DISTANCE_PCT = 0.05    # SL must be at most 5% from entry


def ticker_to_alpaca(ticker: str) -> str:
    """Convert Yahoo-style ticker to Alpaca format. BTC-USD → BTC/USD"""
    if "-" in ticker and ticker.endswith("USD"):
        return ticker.replace("-", "/")
    return ticker


def alpaca_to_ticker(symbol: str) -> str:
    """Convert Alpaca format to Yahoo-style. BTC/USD → BTC-USD"""
    return symbol.replace("/", "-")
