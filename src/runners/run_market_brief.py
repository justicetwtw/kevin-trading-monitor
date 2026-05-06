"""Phase 2.5.9 — 每日 6 次 market brief runner。

讀 BRIEF_TYPE 環境變數
(us_eod / tw_open / tw_close / us_premarket / us_open / us_midday)
→ 組裝 → 送 Telegram。
不走 alert_router(brief 是被動推送)。

Phase 2.5.5:
- dedup:同一台北日 + 同一 brief_type 已推 → skip(避免主+備 cron 雙推)
- 推送成功才標記
- 7 天前 dedup 紀錄自動清除

Sprint 2.5.9:
- 從 4 種擴充到 6 種(加 tw_open + us_open)
- tw_eod → tw_close(命名修正);讀檔時自動 migration
- 凌晨兩則(us_eod / us_midday)→ disable_notification=True (兩人都 silent)
- 移除 DST 變體切換(us_premarket_to_intraday / us_midday_to_afterhours);
  新時間表已避開「推送時段跨越市場 phase」的問題,DST 變體不再需要。
- get_market_state() 留作 logging 用,不再 resolve actual_brief_type。
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytz
from loguru import logger

from src.alerts.brief_generator import VALID_BRIEF_TYPES, BriefGenerator
from src.alerts.telegram_bot import send_telegram
from src.config.settings import TIMEZONE_USER

US_EASTERN = pytz.timezone("America/New_York")

DEDUP_PATH = Path("data_store/brief_sent_today.json")

# 凌晨兩則:Lisa 不要被吵醒
SILENT_BRIEF_TYPES = {"us_eod", "us_midday"}


def _migrate_dedup_keys(state: dict) -> dict:
    """Sprint 2.5.9 migration: tw_eod → tw_close。

    舊資料(2026-05-04 / 2026-05-05 等)的 tw_eod key 自動 rename 為 tw_close。
    """
    for date_key, brief_marks in state.items():
        if isinstance(brief_marks, dict) and "tw_eod" in brief_marks:
            # 若已有 tw_close,以 OR 合併;否則直接 rename
            existing = brief_marks.get("tw_close", False)
            brief_marks["tw_close"] = bool(existing) or bool(brief_marks.pop("tw_eod"))
    return state


def _load_dedup() -> dict:
    if not DEDUP_PATH.exists():
        return {}
    try:
        data = json.loads(DEDUP_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return _migrate_dedup_keys(data)


def is_already_sent_today(brief_type: str) -> bool:
    data = _load_dedup()
    today_taipei = datetime.now(TIMEZONE_USER).strftime("%Y-%m-%d")
    return data.get(today_taipei, {}).get(brief_type, False)


def mark_sent(brief_type: str) -> None:
    today_taipei = datetime.now(TIMEZONE_USER).strftime("%Y-%m-%d")
    data = _load_dedup()
    if today_taipei not in data:
        data[today_taipei] = {}
    data[today_taipei][brief_type] = True

    cutoff = datetime.now(TIMEZONE_USER).date() - timedelta(days=7)
    data = {
        k: v for k, v in data.items()
        if datetime.strptime(k, "%Y-%m-%d").date() >= cutoff
    }

    DEDUP_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEDUP_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def get_market_state() -> dict:
    """返回美股當前 phase + DST 狀態(logging / 觀測用,不再 dispatch)。

    phase: premarket / intraday / afterhours
    is_dst: 是否處於夏令時間
    """
    now_et = datetime.now(US_EASTERN)
    is_dst = now_et.dst().total_seconds() > 0
    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)

    if now_et < market_open:
        return {
            "phase": "premarket",
            "minutes_to_open": (market_open - now_et).total_seconds() / 60,
            "is_dst": is_dst,
            "et_time": now_et.strftime("%H:%M ET"),
        }
    if now_et < market_close:
        return {
            "phase": "intraday",
            "minutes_into_session": (now_et - market_open).total_seconds() / 60,
            "is_dst": is_dst,
            "et_time": now_et.strftime("%H:%M ET"),
        }
    return {
        "phase": "afterhours",
        "minutes_after_close": (now_et - market_close).total_seconds() / 60,
        "is_dst": is_dst,
        "et_time": now_et.strftime("%H:%M ET"),
    }


def is_silent(brief_type: str) -> bool:
    """判斷此 brief 是否為凌晨 silent 推送(不響鈴,進通知區)。

    sprint 2.5.9:us_eod (台北 05:30) + us_midday (台北 02:00) 兩則 silent,
    避免吵醒 Lisa。
    """
    return brief_type in SILENT_BRIEF_TYPES


def main() -> int:
    brief_type = os.getenv("BRIEF_TYPE", "us_eod")
    if brief_type not in VALID_BRIEF_TYPES:
        logger.error(
            f"Invalid BRIEF_TYPE: {brief_type} "
            f"(valid: {sorted(VALID_BRIEF_TYPES)})"
        )
        return 1

    if is_already_sent_today(brief_type):
        logger.info(f"Brief {brief_type} already sent today, skip (dedup)")
        return 0

    market = get_market_state()
    silent = is_silent(brief_type)

    logger.info(
        f"=== run_market_brief start "
        f"(brief_type={brief_type}, market_phase={market['phase']}, "
        f"dst={market['is_dst']}, silent={silent}) ==="
    )
    try:
        message = BriefGenerator(brief_type).generate()
    except Exception as e:
        logger.error(f"brief generation crashed: {e}")
        return 1

    success = send_telegram(message, parse_mode="HTML", disable_notification=silent)
    if not success:
        logger.error(f"Brief {brief_type} send failed")
        return 1

    mark_sent(brief_type)
    logger.info(
        f"=== run_market_brief done (brief_type={brief_type}, "
        f"silent={silent}, marked) ==="
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
