"""Telegram Bot 封裝 - 簡單 send_message 介面。

Phase 2.5.7:
- 支援多 chat_id(逗號分隔的 TELEGRAM_CHAT_ID env)
- send_message 對列表內每個 chat_id 都嘗試推送
- 部分成功(any True)即視為成功(避免一個 chat 失效拖垮整體流程)

Phase 2.5.7 hotfix:
- 改用 httpx 直接打 Telegram API(不依賴 python-telegram-bot library)
- 顯式 30 秒 timeout,迴圈推送多 chat 不會 stuck
- 所有 chat 共用一個 AsyncClient(connection 重用)
"""

import asyncio

import httpx
from loguru import logger

from src.config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS

TELEGRAM_API_BASE = "https://api.telegram.org"
DEFAULT_TIMEOUT_SEC = 30.0


class TelegramNotifier:
    """Telegram 推播封裝(支援多 chat_id,直接 HTTP API)。"""

    def __init__(self, token: str = None, chat_ids=None, chat_id=None):
        """
        chat_ids: list[str] — 主要參數
        chat_id : str       — 舊版單值,相容用;chat_ids 為 None 才考慮
        """
        self.token = token or TELEGRAM_BOT_TOKEN
        if chat_ids is not None:
            self.chat_ids = list(chat_ids) if not isinstance(chat_ids, str) else [chat_ids]
        elif chat_id is not None:
            self.chat_ids = [chat_id] if chat_id else []
        else:
            self.chat_ids = list(TELEGRAM_CHAT_IDS)

        if not self.token or not self.chat_ids:
            raise ValueError(
                "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_IDS must be set"
            )

    async def send_message_async(
        self,
        text: str,
        parse_mode: str = "HTML",
        disable_notification: bool = False,
    ) -> bool:
        """對所有 chat_id 推送(共用一個 AsyncClient)。任一成功即回 True。"""
        url = f"{TELEGRAM_API_BASE}/bot{self.token}/sendMessage"
        results = []
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SEC) as client:
            for cid in self.chat_ids:
                payload = {
                    "chat_id": cid,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_notification": disable_notification,
                }
                try:
                    resp = await client.post(url, json=payload)
                    if resp.status_code == 200:
                        logger.info(f"Telegram sent to {cid}: {text[:50]}...")
                        results.append(True)
                    else:
                        logger.error(
                            f"Telegram failed for {cid}: "
                            f"HTTP {resp.status_code} {resp.text[:200]}"
                        )
                        results.append(False)
                except httpx.HTTPError as e:
                    logger.error(f"Telegram failed for {cid}: {e}")
                    results.append(False)
                except Exception as e:
                    logger.error(f"Telegram unexpected error for {cid}: {e}")
                    results.append(False)
        return any(results)

    def send_message(self, text: str, **kwargs) -> bool:
        """同步包裝(GitHub Actions 用)。"""
        return asyncio.run(self.send_message_async(text, **kwargs))


def send_telegram(text: str, **kwargs) -> bool:
    """便捷函數。"""
    notifier = TelegramNotifier()
    return notifier.send_message(text, **kwargs)
