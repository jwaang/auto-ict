"""Trade journal — JSON persistence for trades, no-trade decisions, and statistics."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from config import TRADE_LOG_PATH


def _ensure_log_file():
    """Create the log file with initial structure if it doesn't exist."""
    path = Path(TRADE_LOG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        data = {"trades": [], "conditional_entries": [], "no_trade_decisions": [], "metadata": {}}
        path.write_text(json.dumps(data, indent=2))


def _load() -> dict:
    _ensure_log_file()
    with open(TRADE_LOG_PATH) as f:
        return json.load(f)


def _save(data: dict):
    with open(TRADE_LOG_PATH, "w") as f:
        json.dump(data, f, indent=2, default=str)


def log_trade(
    ticker: str,
    position: dict,
    ai_decision: dict,
    ict_context: dict,
    account_before: float,
    account_after: float,
) -> str:
    """Log a trade entry (open or closed).

    Returns the trade ID.
    """
    data = _load()
    trade_id = str(uuid.uuid4())[:8]

    entry = {
        "id": trade_id,
        "timestamp_opened": position.get("entry_time", datetime.now(timezone.utc).isoformat()),
        "timestamp_closed": position.get("exit_time"),
        "ticker": ticker,
        "direction": position.get("direction"),
        "entry_price": position.get("entry_price"),
        "stop_loss": position.get("stop_loss"),
        "take_profit": position.get("take_profit"),
        "quantity": position.get("quantity"),
        "risk_amount": position.get("risk_amount"),
        "exit_price": position.get("exit_price"),
        "exit_reason": position.get("exit_reason"),
        "pnl_dollars": position.get("pnl_dollars"),
        "pnl_pct": position.get("pnl_pct"),
        "account_balance_before": round(account_before, 2),
        "account_balance_after": round(account_after, 2),
        "ai_decision": {
            "decision": ai_decision.get("decision"),
            "confidence": ai_decision.get("confidence"),
            "reasoning": ai_decision.get("reasoning"),
            "ict_concepts_used": ai_decision.get("ict_concepts_used", []),
            "setup_type": ai_decision.get("setup_type"),
            "htf_bias": ai_decision.get("htf_bias"),
            "invalidation": ai_decision.get("invalidation"),
            "risk_reward_ratio": ai_decision.get("risk_reward_ratio"),
        },
        "ict_context_snapshot": _summarize_context(ict_context),
        "status": position.get("status", "OPEN"),
        "broker_type": position.get("broker_type", "simulated"),
        "broker_order_ids": position.get("broker_order_ids"),
    }

    data["trades"].append(entry)
    _update_metadata(data)
    _save(data)
    return trade_id


def update_trade_close(trade_id: str, fill_info: dict, account_after: float):
    """Update a trade entry with exit information."""
    data = _load()
    for trade in data["trades"]:
        if trade["id"] == trade_id:
            trade["timestamp_closed"] = datetime.now(timezone.utc).isoformat()
            trade["exit_price"] = fill_info.get("exit_price")
            trade["exit_reason"] = fill_info.get("exit_reason")
            trade["pnl_dollars"] = fill_info.get("pnl_dollars")
            trade["pnl_pct"] = fill_info.get("pnl_pct")
            trade["account_balance_after"] = round(account_after, 2)
            trade["status"] = "CLOSED"
            break
    _update_metadata(data)
    _save(data)


def log_no_trade(ticker: str, ai_decision: dict, ict_context: dict, confluence_score: int):
    """Log a NO_TRADE decision with reasoning."""
    data = _load()
    entry = {
        "id": str(uuid.uuid4())[:8],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ticker": ticker,
        "reasoning": ai_decision.get("reasoning", "No reasoning provided"),
        "confidence": ai_decision.get("confidence", 0),
        "htf_bias": ai_decision.get("htf_bias", "unknown"),
        "ict_concepts_used": ai_decision.get("ict_concepts_used", []),
        "confluence_score": confluence_score,
        "ict_context_snapshot": _summarize_context(ict_context),
    }
    data["no_trade_decisions"].append(entry)
    _update_metadata(data)
    _save(data)


def log_conditional_entry(
    ticker: str,
    ai_decision: dict,
    ict_context: dict,
    confluence_score: int,
) -> str:
    """Log a conditional entry (zones to watch for future entry).

    Returns the conditional entry ID.
    """
    data = _load()
    cond_id = str(uuid.uuid4())[:8]

    direction = ai_decision.get("decision", "").replace("CONDITIONAL_", "")
    entry_zones = ai_decision.get("entry_zones", [])

    entry = {
        "id": cond_id,
        "timestamp_created": datetime.now(timezone.utc).isoformat(),
        "ticker": ticker,
        "direction": direction,
        "status": "WATCHING",  # WATCHING, TRIGGERED, EXPIRED, INVALIDATED
        "confidence": ai_decision.get("confidence", 0),
        "reasoning": ai_decision.get("reasoning", ""),
        "setup_type": ai_decision.get("setup_type", ""),
        "htf_bias": ai_decision.get("htf_bias", ""),
        "invalidation": ai_decision.get("invalidation", ""),
        "ict_concepts_used": ai_decision.get("ict_concepts_used", []),
        "confluence_score": confluence_score,
        "entry_zones": entry_zones,
        "ict_context_snapshot": _summarize_context(ict_context),
        "triggered_zone": None,
        "triggered_at": None,
        "confirmation_signals": None,
    }

    # Ensure conditional_entries key exists (backwards compat)
    if "conditional_entries" not in data:
        data["conditional_entries"] = []

    data["conditional_entries"].append(entry)
    _update_metadata(data)
    _save(data)
    return cond_id


def get_active_conditionals(ticker: str = None) -> list[dict]:
    """Get all conditional entries with status WATCHING."""
    data = _load()
    conditionals = data.get("conditional_entries", [])
    active = [c for c in conditionals if c.get("status") == "WATCHING"]
    if ticker:
        active = [c for c in active if c["ticker"] == ticker]
    return active


def get_open_trade_count() -> int:
    """Get the number of currently open trades from the journal."""
    data = _load()
    return len([t for t in data.get("trades", []) if t.get("status") == "OPEN"])


def update_conditional_status(cond_id: str, status: str, extra: dict = None):
    """Update a conditional entry's status."""
    data = _load()
    for c in data.get("conditional_entries", []):
        if c["id"] == cond_id:
            c["status"] = status
            if extra:
                c.update(extra)
            break
    _save(data)


def log_low_confluence(ticker: str, confluence_score: int, ict_context: dict):
    """Log when confluence score is too low to even call the AI."""
    data = _load()
    entry = {
        "id": str(uuid.uuid4())[:8],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ticker": ticker,
        "reasoning": f"Confluence score {confluence_score}/100 below minimum threshold. AI not consulted.",
        "confluence_score": confluence_score,
        "ict_context_snapshot": _summarize_context(ict_context),
    }
    data["no_trade_decisions"].append(entry)
    _save(data)


def load_journal() -> dict:
    """Load the full trade journal."""
    return _load()


def get_stats() -> dict:
    """Calculate trading statistics from the journal."""
    data = _load()
    trades = [t for t in data["trades"] if t.get("status") == "CLOSED"]

    if not trades:
        return {
            "total_trades": 0,
            "open_trades": len([t for t in data["trades"] if t.get("status") == "OPEN"]),
            "no_trade_decisions": len(data.get("no_trade_decisions", [])),
        }

    wins = [t for t in trades if (t.get("pnl_dollars") or 0) > 0]
    losses = [t for t in trades if (t.get("pnl_dollars") or 0) <= 0]

    total_profit = sum(t.get("pnl_dollars", 0) for t in wins)
    total_loss = abs(sum(t.get("pnl_dollars", 0) for t in losses))

    rrs = [
        abs(t["exit_price"] - t["entry_price"]) / abs(t["entry_price"] - t["stop_loss"])
        for t in trades
        if t.get("exit_price") and t.get("entry_price") and t.get("stop_loss")
        and t["entry_price"] != t["stop_loss"]
    ]

    return {
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0,
        "total_profit": round(total_profit, 2),
        "total_loss": round(total_loss, 2),
        "net_pnl": round(total_profit - total_loss, 2),
        "profit_factor": round(total_profit / total_loss, 2) if total_loss > 0 else float("inf"),
        "avg_rr": round(sum(rrs) / len(rrs), 2) if rrs else 0,
        "best_trade": round(max(t.get("pnl_dollars", 0) for t in trades), 2),
        "worst_trade": round(min(t.get("pnl_dollars", 0) for t in trades), 2),
        "open_trades": len([t for t in data["trades"] if t.get("status") == "OPEN"]),
        "no_trade_decisions": len(data.get("no_trade_decisions", [])),
    }


def _summarize_context(ctx: dict) -> dict:
    """Create a compact snapshot of ICT context for the journal."""
    if not ctx:
        return {}
    analyses = ctx.get("analyses", {})
    summary = {
        "htf_bias": ctx.get("htf_bias"),
        "confluence_score": ctx.get("confluence_score"),
        "is_crypto": ctx.get("is_crypto"),
    }
    for tf_label, tf_data in analyses.items():
        summary[f"{tf_label}_fvg_count"] = len(tf_data.get("unfilled_fvgs", []))
        summary[f"{tf_label}_ob_count"] = len(tf_data.get("unmitigated_obs", []))
        summary[f"{tf_label}_displacement_count"] = len(tf_data.get("displacements", []))
        summary[f"{tf_label}_bias"] = tf_data.get("bias")
        summary[f"{tf_label}_kill_zone"] = tf_data.get("kill_zone")
        pd_zone = tf_data.get("premium_discount", {})
        summary[f"{tf_label}_zone"] = pd_zone.get("zone")
        # New fields (additive — old entries without these are unaffected)
        pdhl = tf_data.get("previous_high_low", {})
        if pdhl.get("pdh") is not None:
            summary[f"{tf_label}_pdh"] = pdhl["pdh"]
        if pdhl.get("pdl") is not None:
            summary[f"{tf_label}_pdl"] = pdhl["pdl"]
        if pdhl.get("pwh") is not None:
            summary[f"{tf_label}_pwh"] = pdhl["pwh"]
        if pdhl.get("pwl") is not None:
            summary[f"{tf_label}_pwl"] = pdhl["pwl"]
        summary[f"{tf_label}_mss_count"] = len(tf_data.get("mss_events", []))
        summary[f"{tf_label}_silver_bullet"] = tf_data.get("silver_bullet")
    return summary


def _update_metadata(data: dict):
    """Update journal metadata."""
    trades = data.get("trades", [])
    closed = [t for t in trades if t.get("status") == "CLOSED"]
    data["metadata"] = {
        "total_trades": len(trades),
        "closed_trades": len(closed),
        "open_trades": len(trades) - len(closed),
        "no_trade_decisions": len(data.get("no_trade_decisions", [])),
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
    if closed:
        # Sort by close timestamp to get the most recently CLOSED trade's balance
        sorted_closed = sorted(
            [t for t in closed if t.get("account_balance_after") and t.get("timestamp_closed")],
            key=lambda t: t.get("timestamp_closed", ""),
            reverse=True,
        )
        if sorted_closed:
            data["metadata"]["current_balance"] = sorted_closed[0]["account_balance_after"]
