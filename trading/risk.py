"""Risk management validation for trade decisions."""

from backtest import params
from config import (
    FUTURES_MAX_SL_DISTANCE_POINTS,
    FUTURES_MIN_SL_DISTANCE_POINTS,
    MAX_CONCURRENT_POSITIONS,
    MAX_SL_DISTANCE_PCT,
    MIN_RR_RATIO,
    MIN_SL_DISTANCE_PCT,
    RISK_PER_TRADE_PCT,
    is_futures,
)
from trading.account import Account


def validate_trade(
    decision: dict,
    account: Account,
    open_position_count: int = 0,
    ticker: str = "",
) -> tuple[bool, str]:
    """Validate a trade decision against risk management rules.

    Args:
        decision: AI trade decision dict
        account: Current account
        open_position_count: Number of currently open positions
        ticker: Ticker symbol (used for futures-specific validation)

    Returns:
        (is_valid, reason_if_invalid)
    """
    if decision.get("decision") == "NO_TRADE":
        return False, "AI decided NO_TRADE"

    entry = decision.get("entry_price")
    sl = decision.get("stop_loss")
    tp = decision.get("take_profit")

    if entry is None or sl is None or tp is None:
        return False, "Missing entry_price, stop_loss, or take_profit"

    if entry <= 0 or sl <= 0 or tp <= 0:
        return False, "Price levels must be positive"

    # Validate stop loss direction
    direction = decision.get("decision")
    if direction == "LONG" and sl >= entry:
        return False, f"LONG trade: stop_loss ({sl}) must be below entry ({entry})"
    if direction == "SHORT" and sl <= entry:
        return False, f"SHORT trade: stop_loss ({sl}) must be above entry ({entry})"

    # Validate take profit direction
    if direction == "LONG" and tp <= entry:
        return False, f"LONG trade: take_profit ({tp}) must be above entry ({entry})"
    if direction == "SHORT" and tp >= entry:
        return False, f"SHORT trade: take_profit ({tp}) must be below entry ({entry})"

    # R:R validation
    risk = abs(entry - sl)
    reward = abs(tp - entry)
    if risk == 0:
        return False, "Stop loss equals entry price"
    # The R:R floor is enforced here as well as in rules.decide_trade, so both
    # must read the same override or a sweep of it silently does nothing.
    min_rr = params.get("min_rr_ratio", MIN_RR_RATIO)
    rr = reward / risk
    if rr < min_rr:
        return False, f"R:R {rr:.2f} below minimum {min_rr}"

    # SL distance bounds — futures use point-based, others use percentage-based
    if is_futures(ticker):
        sl_points = risk  # For futures, risk is already in points
        min_pts = params.get("futures_min_sl_points", FUTURES_MIN_SL_DISTANCE_POINTS)
        max_pts = params.get("futures_max_sl_points", FUTURES_MAX_SL_DISTANCE_POINTS)
        if sl_points < min_pts:
            return False, f"SL too tight: {sl_points:.1f} pts < {min_pts} pts"
        if sl_points > max_pts:
            return False, f"SL too wide: {sl_points:.1f} pts > {max_pts} pts"
    else:
        sl_pct = risk / entry
        if sl_pct < MIN_SL_DISTANCE_PCT:
            return False, f"SL too tight: {sl_pct:.4f} < {MIN_SL_DISTANCE_PCT}"
        if sl_pct > MAX_SL_DISTANCE_PCT:
            return False, f"SL too wide: {sl_pct:.4f} > {MAX_SL_DISTANCE_PCT}"

    # Position count
    if open_position_count >= MAX_CONCURRENT_POSITIONS:
        return False, f"Max concurrent positions ({MAX_CONCURRENT_POSITIONS}) reached"

    # Account risk
    risk_amount = account.get_risk_amount()
    total_risk_pct = (open_position_count + 1) * RISK_PER_TRADE_PCT
    if total_risk_pct > MAX_CONCURRENT_POSITIONS * RISK_PER_TRADE_PCT:
        return False, f"Total risk {total_risk_pct}% exceeds limit"

    # Circuit breaker
    if account.is_circuit_breaker_hit():
        return False, f"Circuit breaker: drawdown {account.get_drawdown_pct()}% exceeds limit"

    return True, "Valid"


def calc_risk_reward(entry: float, stop_loss: float, take_profit: float) -> float:
    """Calculate reward-to-risk ratio."""
    risk = abs(entry - stop_loss)
    reward = abs(take_profit - entry)
    if risk == 0:
        return 0.0
    return round(reward / risk, 2)
