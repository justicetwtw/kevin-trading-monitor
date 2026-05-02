"""手動觸發 Telegram 測試訊息

用法:
    cd kevin-trading-monitor
    export TELEGRAM_BOT_TOKEN=...
    export TELEGRAM_CHAT_ID=...
    python -m scripts.test_telegram
"""

import sys
from datetime import datetime

from src.alerts.telegram_bot import send_telegram
from src.config.settings import VERSION, PROJECT_NAME, TIMEZONE_USER


def main() -> int:
    now = datetime.now(TIMEZONE_USER)
    message = (
        f"🧪 <b>Manual Test — {PROJECT_NAME} v{VERSION}</b>\n"
        f"\n"
        f"⏰ {now.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
        f"\n"
        f"從本機 scripts/test_telegram.py 觸發。"
    )
    return 0 if send_telegram(message) else 1


if __name__ == "__main__":
    sys.exit(main())
