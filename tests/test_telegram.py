"""Telegram 連線測試"""

import os
import pytest
from src.alerts.telegram_bot import TelegramNotifier


def test_token_and_chat_id_required():
    """缺 token 或 chat_id 應該丟 ValueError"""
    with pytest.raises(ValueError):
        TelegramNotifier(token="", chat_id="")


@pytest.mark.skipif(
    not os.getenv("TELEGRAM_BOT_TOKEN") or not os.getenv("TELEGRAM_CHAT_ID"),
    reason="TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 未設定 - 跳過實連測試",
)
def test_send_message_live():
    """實際發送一則測試訊息(需 GitHub Secrets 設定)"""
    notifier = TelegramNotifier()
    result = notifier.send_message(
        "🧪 <b>pytest test_send_message_live</b>\n\n從單元測試發出。"
    )
    assert result is True
