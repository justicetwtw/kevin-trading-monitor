"""帳戶回撤防線 -10 / -20 / -30 + 純讀介面。

主名:update_account_value(current_value)  — 寫檔 + 觸發判斷
純讀:get_current_drawdown() -> dict        — 不寫檔,給 veto_checker context
"""

from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from src.config.thresholds import ACCOUNT_DRAWDOWN_LEVELS
from src.storage.state_manager import read_json, write_json

DRAWDOWN_FILE = "drawdown_history.json"


def _classify(drawdown_pct: float) -> tuple[str, Optional[str]]:
    if drawdown_pct <= ACCOUNT_DRAWDOWN_LEVELS["level_3"]:
        return "level_3", "防守模式:平所有 short premium"
    if drawdown_pct <= ACCOUNT_DRAWDOWN_LEVELS["level_2"]:
        return "level_2", "強制檢視 LEAPS,-30% 以上者考慮減半"
    if drawdown_pct <= ACCOUNT_DRAWDOWN_LEVELS["level_1"]:
        return "level_1", "暫停加碼,全面檢視"
    return "normal", None


def update_account_value(current_value: float) -> dict:
    """更新帳戶高點與當前回撤,寫入 data_store/drawdown_history.json。"""
    history = read_json(DRAWDOWN_FILE, default={"peak": 0, "current": 0})
    if current_value > history.get("peak", 0):
        history["peak"] = current_value
    history["current"] = current_value
    history["last_updated"] = datetime.now(timezone.utc).isoformat()

    peak = history.get("peak") or 0
    drawdown = (current_value - peak) / peak if peak else 0.0
    history["drawdown_pct"] = drawdown

    level, action = _classify(drawdown)
    history["alert_level"] = level
    history["action"] = action

    write_json(DRAWDOWN_FILE, history)
    return history


def get_current_drawdown() -> dict:
    """純讀介面:不寫檔。冷啟動(無歷史檔)→ drawdown_pct=None / alert_level='normal'。"""
    history = read_json(DRAWDOWN_FILE, default={})
    peak = history.get("peak")
    current = history.get("current")
    if not peak:
        return {
            "peak": peak,
            "current": current,
            "drawdown_pct": None,
            "alert_level": "normal",
        }
    drawdown = (current - peak) / peak if (current is not None and peak) else None
    if drawdown is None:
        return {"peak": peak, "current": current, "drawdown_pct": None,
                "alert_level": "normal"}
    level, _ = _classify(drawdown)
    return {
        "peak": peak,
        "current": current,
        "drawdown_pct": drawdown,
        "alert_level": level,
    }
