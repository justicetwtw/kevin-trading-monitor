"""Phase 2.5.5 — Brief sanity check runner。

每天 23:00 / 23:30 台北時間檢查當日預期 brief 是否都送達。
依台北 weekday 與時段決定哪些 brief_type 該已送出,缺的就推一則告警。

dedup 紀錄 source:data_store/brief_sent_today.json(由 run_market_brief.mark_sent 寫入)。
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from loguru import logger

from src.alerts.telegram_bot import send_telegram
from src.config.settings import TIMEZONE_USER

DEDUP_PATH = Path("data_store/brief_sent_today.json")

# 各 brief_type 該在台北時間幾點之前推完(寬限視窗)
EXPECTED_BY_HOUR = {
    "us_eod": 10,        # 主 cron 08:30 → 給到 10:00 算正常
    "tw_eod": 15,        # 主 cron 13:30 → 給到 15:00 算正常
    "us_premarket": 23,  # 主 cron 21:00 → 給到 23:00 算正常
    "us_midday": 8,      # 主 cron 06:00 → 給到 08:00 算正常
}


def _load_sent_today() -> dict:
    if not DEDUP_PATH.exists():
        return {}
    try:
        data = json.loads(DEDUP_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    today_str = datetime.now(TIMEZONE_USER).strftime("%Y-%m-%d")
    return data.get(today_str, {})


def _expected_today(now_taipei: datetime) -> list:
    weekday = now_taipei.weekday()  # 0=Mon, 6=Sun
    hour = now_taipei.hour
    expected: list = []
    if weekday in (0, 1, 2, 3, 4) and hour >= EXPECTED_BY_HOUR["tw_eod"]:
        expected.append("tw_eod")
    if weekday in (0, 1, 2, 3, 4) and hour >= EXPECTED_BY_HOUR["us_premarket"]:
        expected.append("us_premarket")
    if weekday in (1, 2, 3, 4, 5) and hour >= EXPECTED_BY_HOUR["us_eod"]:
        expected.append("us_eod")
    if weekday in (1, 2, 3, 4, 5) and hour >= EXPECTED_BY_HOUR["us_midday"]:
        expected.append("us_midday")
    return expected


def main() -> int:
    now_taipei = datetime.now(TIMEZONE_USER)
    today_str = now_taipei.strftime("%Y-%m-%d")

    sent_today = _load_sent_today()
    expected = _expected_today(now_taipei)
    missing = [bt for bt in expected if not sent_today.get(bt, False)]

    if not missing:
        logger.info(
            f"All expected briefs sent today ({today_str}, {len(expected)} expected)"
        )
        return 0

    message = (
        "⚠ <b>Brief 觸發異常</b>\n\n"
        f"今日 {today_str} 預期推送但未送達:\n"
        + "\n".join(f"  • {bt}" for bt in missing)
        + "\n\n可能原因:GitHub schedule throttle\n"
          "可至 Actions 頁面手動 dispatch 補推"
    )
    success = send_telegram(message, parse_mode="HTML")
    if not success:
        logger.error("Sanity alert send failed")
        return 1
    logger.warning(f"Missing briefs: {missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
