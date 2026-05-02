"""訊號路由:dedup → priority → daily quota + 1min cooldown → telegram → mark sent。

state schema (alert_routing_state.json):
{
  "daily_quota": {"<台北日期 YYYY-MM-DD>": {"P0": int, "P1": int, "P2": int, "P3": int}},
  "last_send_per_key": {"<symbol>::<signal_type>": "<UTC iso>"}
}

每日 quota:
- P0 ≤ 5 / 日,P1 ≤ 10 / 日,P2 / P3 = None(不推,進日報)
- 日期以台北時間 (TIMEZONE_USER) 為界,跨日自動歸零

冷卻:同 key 1 分鐘內第二次推 → 擋(防 routing loop / bug)
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


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


# ============================
# Priority
# ============================

def determine_priority(alert: dict) -> str:
    """依 kind / source / form_type / alert_level 判 P0/P1/P2/P3。

    優先級判定:
    1. drawdown level_2/3 → P0
    2. Trump tier 1 → P0
    3. SEC 8-K / 10-K → P0
    4. alert_level red → P0
    5. alert_level orange / green → P1
    6. alert_level yellow → P2
    7. 其他 / white → P3
    """
    kind = alert.get("kind") or ""
    src = str(alert.get("source", "")).lower()

    if kind == "drawdown" and alert.get("level") in ("level_2", "level_3"):
        return "P0"
    if "trump" in src and alert.get("tier") == 1:
        return "P0"
    if "sec" in src and alert.get("form_type") in ("8-K", "10-K"):
        return "P0"

    level = alert.get("alert_level", "none")
    if level == "red":
        return "P0"
    if level in ("orange", "green"):
        return "P1"
    if level == "yellow":
        return "P2"
    return "P3"


# ============================
# Quota / cooldown
# ============================

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
        # 跨日歸零(舊日期保留供 audit,但只查今日)
        daily[today] = {}
    return daily[today]


def should_send(alert: dict, priority: str) -> bool:
    """檢查 daily quota + 1 分鐘冷卻。"""
    try:
        limit = DAILY_PUSH_LIMITS.get(priority)
        if limit is None:
            return False  # P2 / P3 不推

        state = _read_state()
        today_quota = _quota_for_today(state)
        used = int(today_quota.get(priority, 0) or 0)
        if used >= limit:
            logger.info(f"daily quota for {priority} reached ({used}/{limit})")
            return False

        last = state["last_send_per_key"].get(_key(alert))
        last_dt = _parse_iso(last)
        if last_dt is not None:
            elapsed = (_now_utc() - last_dt).total_seconds()
            if elapsed < COOLDOWN_SECONDS:
                logger.info(f"1min cooldown active for {_key(alert)} ({elapsed:.0f}s)")
                return False
        return True
    except Exception as e:
        logger.error(f"should_send failed (assume not sending): {e}")
        return False


def mark_sent_quota(alert: dict, priority: str) -> None:
    """成功推播後扣 quota + 紀錄 last_send_per_key。"""
    try:
        state = _read_state()
        today_quota = _quota_for_today(state)
        today_quota[priority] = int(today_quota.get(priority, 0) or 0) + 1
        state["last_send_per_key"][_key(alert)] = _now_utc().isoformat()

        # 清理超過 7 天的 daily_quota 舊日期
        cutoff = (datetime.now(TIMEZONE_USER) - timedelta(days=7)).date()
        state["daily_quota"] = {
            d: q for d, q in state["daily_quota"].items()
            if _safe_parse_date(d) is None or _safe_parse_date(d) >= cutoff
        }
        # 清理超過 7 天的 last_send_per_key
        old_cutoff = _now_utc() - timedelta(days=7)
        state["last_send_per_key"] = {
            k: v for k, v in state["last_send_per_key"].items()
            if (_parse_iso(v) or _now_utc()) > old_cutoff
        }

        write_json(ROUTING_FILE, state)
    except Exception as e:
        logger.error(f"mark_sent_quota failed: {e}")


def _safe_parse_date(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


# ============================
# 主路由
# ============================

def route_alert(alert: dict) -> bool:
    """主路由:dedup → priority → quota+cooldown → send → mark。"""
    try:
        if is_duplicate(alert):
            logger.info(f"skip duplicate: {_key(alert)}")
            return False

        priority = determine_priority(alert)
        if not should_send(alert, priority):
            return False

        message = alert.get("message") or str(alert)
        ok = send_telegram(message)
        if not ok:
            return False

        mark_sent(alert)
        mark_sent_quota(alert, priority)
        return True
    except Exception as e:
        logger.error(f"route_alert failed: {e}")
        return False
