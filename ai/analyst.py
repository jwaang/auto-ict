"""Claude Code CLI integration for ICT trade analysis.

Uses the `claude` CLI (Claude Code) instead of the Anthropic SDK directly,
so it runs on the user's existing Claude Pro/Max subscription.
"""

import json
import re
import subprocess
import tempfile
from pathlib import Path

from ai.prompt import build_messages, get_system_prompt
from config import CLAUDE_MODEL


def analyze(ict_context: dict, account_state: dict) -> dict:
    """Send ICT context to Claude Code CLI and get a trade decision.

    Args:
        ict_context: Complete ICT analysis from confluence.analyze_multi_timeframe()
        account_state: Current account state (balance, positions)

    Returns:
        Parsed trade decision dict
    """
    messages = build_messages(ict_context, account_state)
    system_prompt = get_system_prompt()
    user_prompt = messages[0]["content"]

    # Combine system + user into a single prompt for the CLI
    full_prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"

    # Write prompt to temp file to avoid shell escaping issues
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(full_prompt)
        prompt_file = f.name

    try:
        result = subprocess.run(
            [
                "claude",
                "-p",
                "--model", CLAUDE_MODEL,
                "--max-turns", "1",
            ],
            input=full_prompt,
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
        )
    except FileNotFoundError:
        raise RuntimeError(
            "Claude Code CLI not found. Install it with: npm install -g @anthropic-ai/claude-code"
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Claude Code CLI timed out after 120 seconds")
    finally:
        Path(prompt_file).unlink(missing_ok=True)

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(f"Claude Code CLI error (exit {result.returncode}): {stderr}")

    raw_text = result.stdout.strip()
    if not raw_text:
        raise RuntimeError("Claude Code CLI returned empty response")

    return _parse_response(raw_text)


def _parse_response(raw_text: str) -> dict:
    """Parse Claude's JSON response, handling markdown wrapping."""
    # Try direct JSON parse first
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code fences
    match = re.search(r"```(?:json)?\s*\n?(.*?)```", raw_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding JSON object in text
    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    # Failed to parse — return a NO_TRADE with the raw response
    return {
        "decision": "NO_TRADE",
        "confidence": 0,
        "reasoning": f"Failed to parse AI response. Raw output: {raw_text[:500]}",
        "entry_price": None,
        "stop_loss": None,
        "take_profit": None,
        "risk_reward_ratio": None,
        "ict_concepts_used": [],
        "htf_bias": "neutral",
        "setup_type": "parse_error",
        "invalidation": "N/A",
        "_parse_error": True,
        "_raw_response": raw_text,
    }
