"""24 小時去重 by symbol+signal_type,含升級 override 與 Trump tag override。

升級規則(突破 dedup):
- alert_level 從 white → yellow / yellow → green / white → green:重推
- 反向(green → yellow → white):仍 dedup,降級不打擾

Trump tag override:
- 同 key 但新訊號含 ⚠Trump_Tier1(舊紀錄沒有)→ 重推(事件 context 已變)

state schema:
{ "<symbol>::<signal_type>": {"last_sent": iso, "alert_level": str, "tags": [...]} }

7 天前舊紀錄寫入時自動清理。
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
    sym = alert.get("symbol", alert.get("source", "unknown"))
    typ = alert.get("signal_type", alert.get("kind", "unknown"))
    return f"{sym}::{typ}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


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


def _is_upgrade(old_level: str | None, new_level: str | None) -> bool:
    if not old_level or not new_level:
        return False
    return _LEVEL_RANK.get(new_level, 0) > _LEVEL_RANK.get(old_level, 0)


def _has_new_trump_tier1(old_tags: list, new_tags: list) -> bool:
    return TRUMP_TIER1_TAG in (new_tags or []) and TRUMP_TIER1_TAG not in (old_tags or [])


def is_duplicate(alert: dict) -> bool:
    """24h dedup,升級 / Trump tag 變化 → 突破。"""
    try:
        state = read_json(DEDUP_FILE, default={})
        if not isinstance(state, dict):
            return False
        rec = state.get(_key(alert))
        if not rec:
            return False

        last_dt = _parse_iso(rec.get("last_sent"))
        if last_dt is None:
            return False
        if (_now() - last_dt) >= timedelta(hours=DEDUP_WINDOW_HOURS):
            return False

        # 24h 內:檢查 override
        new_level = alert.get("alert_level")
        old_level = rec.get("alert_level")
        if _is_upgrade(old_level, new_level):
            return False
        if _has_new_trump_tier1(rec.get("tags") or [], alert.get("tags") or []):
            return False
        return True
    except Exception as e:
        logger.warning(f"is_duplicate failed (assume not duplicate): {e}")
        return False


def mark_sent(alert: dict) -> None:
    """寫入發送紀錄,順便清掉 7 天前舊紀錄。"""
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
        for k, v in state.items():
            if not isinstance(v, dict):
                continue
            dt = _parse_iso(v.get("last_sent"))
            if dt and dt > cutoff:
                cleaned[k] = v
        write_json(DEDUP_FILE, cleaned)
    except Exception as e:
        logger.error(f"mark_sent failed: {e}")
