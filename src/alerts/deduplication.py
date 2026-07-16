"""24-hour alert deduplication with priority-upgrade overrides.

Position alerts may provide an opaque `dedup_key`; this prevents real holdings
from being persisted in the public repository's dedup/routing state files.
"""

from datetime import datetime, timedelta, timezone

from loguru import logger

from src.storage.state_manager import read_json, write_json

DEDUP_FILE = "alert_dedup.json"
DEDUP_WINDOW_HOURS = 24
RETENTION_DAYS = 7

_LEVEL_RANK = {"white": 1, "yellow": 2, "orange": 3, "green": 4, "red": 5}
TRUMP_TIER1_TAG = "⚠Trump_Tier1"


def _key(alert: dict) -> str:
    explicit = alert.get("dedup_key")
    if isinstance(explicit, str) and explicit:
        return explicit
    symbol = alert.get("symbol", alert.get("source", "unknown"))
    signal_type = alert.get("signal_type", alert.get("kind", "unknown"))
    return f"{symbol}::{signal_type}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        return None


def _is_upgrade(old_level: str | None, new_level: str | None) -> bool:
    if not old_level or not new_level:
        return False
    return _LEVEL_RANK.get(new_level, 0) > _LEVEL_RANK.get(old_level, 0)


def _has_new_trump_tier1(old_tags: list, new_tags: list) -> bool:
    return (
        TRUMP_TIER1_TAG in (new_tags or [])
        and TRUMP_TIER1_TAG not in (old_tags or [])
    )


def is_duplicate(alert: dict) -> bool:
    """Deduplicate within 24 hours; escalation and new Tier-1 tags override."""
    try:
        state = read_json(DEDUP_FILE, default={})
        if not isinstance(state, dict):
            return False
        record = state.get(_key(alert))
        if not record:
            return False

        last_sent = _parse_iso(record.get("last_sent"))
        if last_sent is None:
            return False
        if (_now() - last_sent) >= timedelta(hours=DEDUP_WINDOW_HOURS):
            return False

        if _is_upgrade(record.get("alert_level"), alert.get("alert_level")):
            return False
        if _has_new_trump_tier1(
            record.get("tags") or [], alert.get("tags") or []
        ):
            return False
        return True
    except Exception as exc:
        logger.warning(f"is_duplicate failed (assume not duplicate): {exc}")
        return False


def mark_sent(alert: dict) -> None:
    """Persist a minimal dedup record and remove entries older than 7 days."""
    try:
        state = read_json(DEDUP_FILE, default={})
        if not isinstance(state, dict):
            state = {}
        state[_key(alert)] = {
            "last_sent": _now().isoformat(),
            "alert_level": alert.get("alert_level"),
            "tags": list(alert.get("tags") or []),
        }
        cutoff = _now() - timedelta(days=RETENTION_DAYS)
        cleaned = {}
        for key, value in state.items():
            if not isinstance(value, dict):
                continue
            sent_at = _parse_iso(value.get("last_sent"))
            if sent_at and sent_at > cutoff:
                cleaned[key] = value
        write_json(DEDUP_FILE, cleaned)
    except Exception as exc:
        logger.error(f"mark_sent failed: {exc}")
