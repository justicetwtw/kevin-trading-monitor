"""Account drawdown guard with encrypted high-water state.

The repository is public. Exact `peak` and `current` account values are stored
only inside a Fernet token. Public JSON exposes drawdown percentage, alert level
and timestamps, but never account amounts.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from loguru import logger

from src.config.thresholds import ACCOUNT_DRAWDOWN_LEVELS
from src.storage.state_manager import read_json, write_json

DRAWDOWN_FILE = "drawdown_history.json"
POSITION_STATE_KEY_ENV = "POSITION_STATE_KEY"
_EPHEMERAL_KEY = Fernet.generate_key()


def _classify(drawdown_pct: float) -> tuple[str, Optional[str]]:
    if drawdown_pct <= ACCOUNT_DRAWDOWN_LEVELS["level_3"]:
        return "level_3", "防守模式:平所有 short premium"
    if drawdown_pct <= ACCOUNT_DRAWDOWN_LEVELS["level_2"]:
        return "level_2", "強制檢視 LEAPS,-30% 以上者考慮減半"
    if drawdown_pct <= ACCOUNT_DRAWDOWN_LEVELS["level_1"]:
        return "level_1", "暫停加碼,全面檢視"
    return "normal", None


def _fernet() -> tuple[Fernet, str]:
    raw = os.getenv(POSITION_STATE_KEY_ENV, "").strip()
    if raw:
        try:
            return Fernet(raw.encode("utf-8")), "actions_secret"
        except (TypeError, ValueError) as exc:
            logger.error(
                f"{POSITION_STATE_KEY_ENV} is invalid; using ephemeral key: {exc}"
            )
    return Fernet(_EPHEMERAL_KEY), "ephemeral_process"


def _decrypt_private_state(history: dict, fernet: Fernet) -> dict:
    token = history.get("encrypted_state")
    if not isinstance(token, str) or not token:
        return {"peak": 0.0, "current": 0.0}
    try:
        decoded = fernet.decrypt(token.encode("utf-8"))
        value = json.loads(decoded.decode("utf-8"))
        peak = float(value.get("peak", 0.0) or 0.0)
        current = float(value.get("current", 0.0) or 0.0)
        return {"peak": peak, "current": current}
    except (InvalidToken, ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.error(f"encrypted drawdown state could not be read; resetting: {exc}")
        return {"peak": 0.0, "current": 0.0}


def update_account_value(current_value: float) -> dict:
    """Update encrypted peak/current state and write a privacy-safe public record."""
    current_value = float(current_value)
    if current_value < 0:
        raise ValueError("current account value cannot be negative")

    history = read_json(DRAWDOWN_FILE, default={})
    if not isinstance(history, dict):
        history = {}
    fernet, key_source = _fernet()
    private = _decrypt_private_state(history, fernet)

    peak = max(float(private.get("peak", 0.0) or 0.0), current_value)
    drawdown = (current_value - peak) / peak if peak else 0.0
    level, action = _classify(drawdown)
    now = datetime.now(timezone.utc).isoformat()

    encrypted = fernet.encrypt(
        json.dumps(
            {"peak": peak, "current": current_value},
            separators=(",", ":"),
        ).encode("utf-8")
    ).decode("utf-8")

    public_history = {
        "schema_version": 2,
        "encrypted_state": encrypted,
        "drawdown_pct": drawdown,
        "alert_level": level,
        "action": action,
        "last_updated": now,
        "privacy": "fernet_encrypted_account_values",
        "key_source": key_source,
    }
    write_json(DRAWDOWN_FILE, public_history)

    # Return private values only to the current process for compatibility/tests.
    return {
        **public_history,
        "peak": peak,
        "current": current_value,
    }


def get_current_drawdown() -> dict:
    """Read public drawdown state without decrypting account values."""
    history = read_json(DRAWDOWN_FILE, default={})
    if not isinstance(history, dict):
        history = {}
    drawdown = history.get("drawdown_pct")
    if not isinstance(drawdown, (int, float)):
        return {
            "peak": None,
            "current": None,
            "drawdown_pct": None,
            "alert_level": "normal",
        }
    level, _ = _classify(float(drawdown))
    return {
        "peak": None,
        "current": None,
        "drawdown_pct": float(drawdown),
        "alert_level": level,
    }
