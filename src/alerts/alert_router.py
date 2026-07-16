"""Alert routing: dedup → priority → quota/cooldown → Telegram → state.

Sensitive alerts (private positions/account state) use opaque dedup keys and
privacy-aware Telegram logging so public Actions logs/state do not reveal them.
"""

from datetime import datetime, timedelta, timezone

from loguru import logger

from src.alerts.deduplication import _key, is_duplicate, mark_sent
from src.alerts.telegram_bot import send_telegram
from src.config.settings import TIMEZONE_USER
from src.config.thresholds import DAILY_PUSH_LIMITS
from src.storage.state_manager import read_json, write_json

ROUTING_FILE = "alert_routing_state.json"
COOLDOWN_SECONDS = 60


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _today_tw_str() -> str:
    return datetime.now(TIMEZONE_USER).date().isoformat()


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


def determine_priority(alert: dict) -> str:
    """Map an alert to P0/P1/P2/P3."""
    kind = alert.get("kind") or ""
    source = str(alert.get("source", "")).lower()

    if kind == "drawdown" and alert.get("level") in ("level_2", "level_3"):
        return "P0"
    if "trump" in source and alert.get("tier") == 1:
        return "P0"
    if "sec" in source and alert.get("form_type") in ("8-K", "10-K"):
        return "P0"

    level = alert.get("alert_level", "none")
    if level == "red":
        return "P0"
    if level in ("orange", "green"):
        return "P1"
    if level == "yellow":
        return "P2"
    return "P3"


def _read_state() -> dict:
    state = read_json(ROUTING_FILE, default={})
    if not isinstance(state, dict):
        state = {}
    state.setdefault("daily_quota", {})
    state.setdefault("last_send_per_key", {})
    return state


def _quota_for_today(state: dict) -> dict:
    today = _today_tw_str()
    daily = state["daily_quota"]
    if today not in daily:
        daily[today] = {}
    return daily[today]


def should_send(alert: dict, priority: str) -> bool:
    """Apply daily quota and one-minute key cooldown."""
    try:
        limit = DAILY_PUSH_LIMITS.get(priority)
        if limit is None:
            return False

        state = _read_state()
        today_quota = _quota_for_today(state)
        used = int(today_quota.get(priority, 0) or 0)
        if used >= limit:
            logger.info(f"daily quota for {priority} reached ({used}/{limit})")
            return False

        key = _key(alert)
        last = state["last_send_per_key"].get(key)
        last_dt = _parse_iso(last)
        if last_dt is not None:
            elapsed = (_now_utc() - last_dt).total_seconds()
            if elapsed < COOLDOWN_SECONDS:
                logger.info(f"1min cooldown active for {key} ({elapsed:.0f}s)")
                return False
        return True
    except Exception as exc:
        logger.error(f"should_send failed (assume not sending): {exc}")
        return False


def mark_sent_quota(alert: dict, priority: str) -> None:
    """Increment quota and persist only the dedup key and timestamp."""
    try:
        state = _read_state()
        today_quota = _quota_for_today(state)
        today_quota[priority] = int(today_quota.get(priority, 0) or 0) + 1
        state["last_send_per_key"][_key(alert)] = _now_utc().isoformat()

        cutoff = (datetime.now(TIMEZONE_USER) - timedelta(days=7)).date()
        state["daily_quota"] = {
            day: quota
            for day, quota in state["daily_quota"].items()
            if _safe_parse_date(day) is None or _safe_parse_date(day) >= cutoff
        }
        old_cutoff = _now_utc() - timedelta(days=7)
        state["last_send_per_key"] = {
            key: value
            for key, value in state["last_send_per_key"].items()
            if (_parse_iso(value) or _now_utc()) > old_cutoff
        }
        write_json(ROUTING_FILE, state)
    except Exception as exc:
        logger.error(f"mark_sent_quota failed: {exc}")


def _safe_parse_date(value: str):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return None


def route_alert(alert: dict) -> bool:
    """Route one alert; sensitive message text is redacted from CI logs."""
    try:
        if is_duplicate(alert):
            logger.info(f"skip duplicate: {_key(alert)}")
            return False

        priority = determine_priority(alert)
        if not should_send(alert, priority):
            return False

        message = alert.get("message") or str(alert)
        ok = send_telegram(
            message,
            sensitive=bool(alert.get("sensitive")),
        )
        if not ok:
            return False

        mark_sent(alert)
        mark_sent_quota(alert, priority)
        return True
    except Exception as exc:
        logger.error(f"route_alert failed: {exc}")
        return False
