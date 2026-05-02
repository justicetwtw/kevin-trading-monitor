"""Telegram Bot 封裝 - 簡單 send_message 介面"""

import asyncio
from telegram import Bot
from telegram.error import TelegramError
from loguru import logger
from src.config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

class TelegramNotifier:
    """Telegram 推播封裝"""

    def __init__(self, token: str = None, chat_id: str = None):
        self.token = token or TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or TELEGRAM_CHAT_ID
        if not self.token or not self.chat_id:
            raise ValueError(
                "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set"
            )
        self.bot = Bot(token=self.token)

    async def send_message_async(
        self,
        text: str,
        parse_mode: str = "HTML",
        disable_notification: bool = False,
    ) -> bool:
        """非同步發送訊息"""
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=parse_mode,
                disable_notification=disable_notification,
            )
            logger.info(f"Telegram message sent: {text[:50]}...")
            return True
        except TelegramError as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    def send_message(self, text: str, **kwargs) -> bool:
        """同步包裝(GitHub Actions 用)"""
        return asyncio.run(self.send_message_async(text, **kwargs))

def send_telegram(text: str, **kwargs) -> bool:
    """便捷函數"""
    notifier = TelegramNotifier()
    return notifier.send_message(text, **kwargs)
