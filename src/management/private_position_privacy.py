"""Privacy helpers for position alerts persisted by public workflows."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any

from src.management.current_positions import POSITIONS_ENV, load_positions


def private_alert_dedup_key(alert: dict[str, Any], kind: str) -> str:
    """Build a stable opaque key without persisting a position symbol or contract.

    The private positions document is used as the HMAC key. Someone reading the
    public repository cannot reverse or dictionary-test the key without knowing
    the encrypted `POSITIONS_JSON` value (or the local private positions file).
    """
    secret_material = os.getenv(POSITIONS_ENV, "").strip()
    if not secret_material:
        secret_material = json.dumps(
            load_positions(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    identity = {
        "kind": kind,
        "option_id": alert.get("option_id"),
        "symbol": alert.get("symbol"),
        "strike": alert.get("strike"),
        "expiry": alert.get("expiry"),
        "level": alert.get("level"),
    }
    message = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    key = hashlib.sha256(secret_material.encode("utf-8")).digest()
    digest = hmac.new(key, message, hashlib.sha256).hexdigest()[:24]
    return f"private-position::{kind}::{digest}"
