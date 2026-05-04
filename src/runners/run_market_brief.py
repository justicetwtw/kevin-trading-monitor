"""Phase 2.5 — 每日 4 次 market brief runner。

讀 BRIEF_TYPE 環境變數 (us_eod / tw_eod / us_premarket / us_midday) → 組裝 → 送 Telegram。
不走 alert_router(brief 是被動推送)。

Phase 2.5.5:
- dedup:同一台北日 + 同一 brief_type 已推 → skip(避免主+備 cron 雙推)
- 推送成功才標記
- 7 天前 dedup 紀錄自動清除
Phase 2.5.6:
- DST detection:依美股盤實際 phase 切換 brief 變體
  - us_premarket + intraday → us_premarket_to_intraday
  - us_midday + afterhours → us_midday_to_afterhours
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


def is_already_sent_today(brief_type: str) -> bool:
    if not DEDUP_PATH.exists():
        return False
    try:
        data = json.loads(DEDUP_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    today_taipei = datetime.now(TIMEZONE_USER).strftime("%Y-%m-%d")
    return data.get(today_taipei, {}).get(brief_type, False)


def mark_sent(brief_type: str) -> None:
    today_taipei = datetime.now(TIMEZONE_USER).strftime("%Y-%m-%d")
    if DEDUP_PATH.exists():
        try:
            data = json.loads(DEDUP_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    else:
        data = {}
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
    """返回美股當前 phase + DST 狀態。

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


def resolve_actual_brief_type(brief_type: str, market: dict) -> str:
    """根據美股 phase 決定實際要組哪一版 brief。

    us_premarket + intraday → us_premarket_to_intraday(已開盤,給開盤即時)
    us_midday + afterhours → us_midday_to_afterhours(已收盤,給當日收盤完整版)
    其餘原樣返回。
    """
    if brief_type == "us_premarket" and market["phase"] == "intraday":
        logger.info(
            f"DST/timing adjust: us_premarket → intraday "
            f"(et={market['et_time']}, dst={market['is_dst']})"
        )
        return "us_premarket_to_intraday"
    if brief_type == "us_midday" and market["phase"] == "afterhours":
        logger.info(
            f"DST/timing adjust: us_midday → afterhours "
            f"(et={market['et_time']}, dst={market['is_dst']})"
        )
        return "us_midday_to_afterhours"
    return brief_type


def main() -> int:
    brief_type = os.getenv("BRIEF_TYPE", "us_eod")
    if brief_type not in ("us_eod", "tw_eod", "us_premarket", "us_midday"):
        logger.error(f"Invalid BRIEF_TYPE: {brief_type}")
        return 1

    if is_already_sent_today(brief_type):
        logger.info(f"Brief {brief_type} already sent today, skip (dedup)")
        return 0

    market = get_market_state()
    actual_brief_type = resolve_actual_brief_type(brief_type, market)
    if actual_brief_type not in VALID_BRIEF_TYPES:
        logger.error(f"Resolved brief type invalid: {actual_brief_type}")
        return 1

    logger.info(
        f"=== run_market_brief start "
        f"(input={brief_type}, actual={actual_brief_type}, "
        f"market_phase={market['phase']}, dst={market['is_dst']}) ==="
    )
    try:
        message = BriefGenerator(actual_brief_type).generate()
    except Exception as e:
        logger.error(f"brief generation crashed: {e}")
        return 1

    success = send_telegram(message, parse_mode="HTML")
    if not success:
        logger.error(f"Brief {actual_brief_type} send failed")
        return 1

    mark_sent(brief_type)
    logger.info(
        f"=== run_market_brief done (input={brief_type}, "
        f"actual={actual_brief_type}, marked) ==="
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
