"""Phase 2.5 — 每日 4 次 market brief runner。

讀 BRIEF_TYPE 環境變數 (us_eod / tw_eod / us_premarket / us_midday) → 組裝 → 送 Telegram。
不走 alert_router(brief 是被動推送)。
"""

import os
import sys

from loguru import logger

from src.alerts.brief_generator import VALID_BRIEF_TYPES, BriefGenerator
from src.alerts.telegram_bot import send_telegram


def main() -> int:
    brief_type = os.getenv("BRIEF_TYPE", "us_eod")
    if brief_type not in VALID_BRIEF_TYPES:
        logger.error(f"Invalid BRIEF_TYPE: {brief_type}")
        return 1

    logger.info(f"=== run_market_brief start (type={brief_type}) ===")
    try:
        message = BriefGenerator(brief_type).generate()
    except Exception as e:
        logger.error(f"brief generation crashed: {e}")
        return 1

    success = send_telegram(message, parse_mode="HTML")
    if not success:
        logger.error(f"Brief {brief_type} send failed")
        return 1

    logger.info(f"=== run_market_brief done (type={brief_type}) ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
