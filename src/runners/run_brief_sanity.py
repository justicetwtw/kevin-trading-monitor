"""Daily market-brief delivery sanity check in Asia/Taipei.

The check runs at 23:45 / 23:55 Taipei, after the latest U.S. standard-time
opening backup. It verifies dispatch completion, not exchange opening times.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from loguru import logger

from src.alerts.telegram_bot import send_telegram
from src.config.settings import TIMEZONE_USER
from src.runners.us_open_state import (
    DELIVERY_SENT,
    STATE_PATH as US_OPEN_STATE_PATH,
    UsOpenDeliveryStore,
)

DEDUP_PATH = Path("data_store/brief_sent_today.json")

# Brief deadlines in Taipei hours. Actual exchange times:
# - TW regular: 09:00-13:30
# - US daylight: 21:30-04:00 next day
# - US standard: 22:30-05:00 next day
EXPECTED_BY_HOUR = {
    "us_midday": 4,      # primary 01:00 / 02:00, checked Tue-Sat
    "us_eod": 7,         # primary 04:30 / 05:30, checked Tue-Sat
    "tw_open": 10,       # 08:30 pre-open brief; formal open 09:00
    "tw_close": 15,      # primary 13:40; formal close 13:30
    "us_premarket": 19,  # primary 17:00 / 18:00
    "us_open": 23,       # exact open 21:30 / 22:30; backup by 23:00
}


def _load_sent_today() -> dict:
    today_str = datetime.now(TIMEZONE_USER).strftime("%Y-%m-%d")
    sent: dict = {}
    if DEDUP_PATH.exists():
        try:
            data = json.loads(DEDUP_PATH.read_text(encoding="utf-8"))
            sent = dict(data.get(today_str, {}))
        except (json.JSONDecodeError, OSError):
            sent = {}

    # us_open moved to the dedicated SLA delivery state. Treat it as sent when
    # either the new session-keyed store or the legacy boolean says so (the ET
    # session date equals today's Taipei date at the open).
    store = UsOpenDeliveryStore(US_OPEN_STATE_PATH, legacy_path=None)
    record = store.get(f"us_open:{today_str}")
    if record and record.get("delivery_state") == DELIVERY_SENT:
        sent["us_open"] = True
    return sent


def _expected_today(now_taipei: datetime) -> list:
    """Return briefs that should have completed by the current Taipei time."""
    weekday = now_taipei.weekday()  # 0=Mon, 6=Sun
    hour = now_taipei.hour
    expected: list[str] = []

    if weekday in (0, 1, 2, 3, 4):
        for brief_type in (
            "tw_open",
            "tw_close",
            "us_premarket",
            "us_open",
        ):
            if hour >= EXPECTED_BY_HOUR[brief_type]:
                expected.append(brief_type)

    # These belong to the preceding U.S. Mon-Fri session and arrive in Taipei
    # early Tue-Sat.
    if weekday in (1, 2, 3, 4, 5):
        for brief_type in ("us_midday", "us_eod"):
            if hour >= EXPECTED_BY_HOUR[brief_type]:
                expected.append(brief_type)

    return expected


def main() -> int:
    now_taipei = datetime.now(TIMEZONE_USER)
    today_str = now_taipei.strftime("%Y-%m-%d")

    sent_today = _load_sent_today()
    expected = _expected_today(now_taipei)
    missing = [
        brief_type
        for brief_type in expected
        if not sent_today.get(brief_type, False)
    ]

    if not missing:
        logger.info(
            f"All expected briefs sent today "
            f"({today_str}, {len(expected)} expected)"
        )
        return 0

    message = (
        "⚠ <b>Brief 觸發異常</b>\n\n"
        f"今日 {today_str} 預期推送但未送達:\n"
        + "\n".join(f"  • {brief_type}" for brief_type in missing)
        + "\n\n市場時間以台北為準："
        "台股 09:00-13:30；美股夏令 21:30-04:00、"
        "冬令 22:30-05:00。\n"
        "可能原因: GitHub schedule throttle；"
        "可至 Actions 手動 dispatch 補推。"
    )
    success = send_telegram(message, parse_mode="HTML")
    if not success:
        logger.error("Sanity alert send failed")
        return 1
    logger.warning(f"Missing briefs: {missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
