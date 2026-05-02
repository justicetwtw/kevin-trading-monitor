"""健康檢查 - 測試 Telegram 連線並推播 System Online 訊息"""

import sys
from datetime import datetime
from loguru import logger
from src.alerts.telegram_bot import send_telegram
from src.config.settings import VERSION, PROJECT_NAME, TIMEZONE_USER

def main() -> int:
    now = datetime.now(TIMEZONE_USER)
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S %Z")

    message = (
        f"🟢 <b>System Online — {PROJECT_NAME} v{VERSION}</b>\n"
        f"\n"
        f"⏰ {timestamp}\n"
        f"\n"
        f"✅ Telegram 連線正常\n"
        f"✅ GitHub Actions 排程運作中\n"
        f"\n"
        f"系統健康檢查成功"
    )

    success = send_telegram(message)

    if success:
        logger.info("Health check passed")
        return 0
    else:
        logger.error("Health check failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())
