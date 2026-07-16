"""Telegram Bot wrapper with multi-chat support and privacy-aware logging."""

import asyncio

import httpx
from loguru import logger

from src.config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS

TELEGRAM_API_BASE = "https://api.telegram.org"
DEFAULT_TIMEOUT_SEC = 30.0


class TelegramNotifier:
    """Telegram sender for one or more chat IDs."""

    def __init__(self, token: str = None, chat_ids=None, chat_id=None):
        self.token = token or TELEGRAM_BOT_TOKEN
        if chat_ids is not None:
            self.chat_ids = (
                list(chat_ids)
                if not isinstance(chat_ids, str)
                else [chat_ids]
            )
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
        parse_mode: str | None = "HTML",
        disable_notification: bool = False,
        sensitive: bool = False,
    ) -> bool:
        """Send to every chat ID; redact sensitive message text from CI logs.

        `parse_mode=None` sends literal plain text. The field is omitted rather
        than serialized as JSON null, which keeps arbitrary Truth Social text
        from being interpreted as Telegram HTML or Markdown.
        """
        url = f"{TELEGRAM_API_BASE}/bot{self.token}/sendMessage"
        results = []
        async with httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT_SEC
        ) as client:
            for chat_id in self.chat_ids:
                payload = {
                    "chat_id": chat_id,
                    "text": text,
                    "disable_notification": disable_notification,
                }
                if parse_mode:
                    payload["parse_mode"] = parse_mode
                try:
                    response = await client.post(url, json=payload)
                    if response.status_code == 200:
                        preview = (
                            "<sensitive message redacted>"
                            if sensitive
                            else f"{text[:50]}..."
                        )
                        logger.info(
                            f"Telegram sent to {chat_id}: {preview}"
                        )
                        results.append(True)
                    else:
                        logger.error(
                            f"Telegram failed for {chat_id}: "
                            f"HTTP {response.status_code} "
                            f"{response.text[:200]}"
                        )
                        results.append(False)
                except httpx.HTTPError as exc:
                    logger.error(f"Telegram failed for {chat_id}: {exc}")
                    results.append(False)
                except Exception as exc:
                    logger.error(
                        f"Telegram unexpected error for {chat_id}: {exc}"
                    )
                    results.append(False)
        return any(results)

    def send_message(self, text: str, **kwargs) -> bool:
        return asyncio.run(self.send_message_async(text, **kwargs))


def send_telegram(text: str, **kwargs) -> bool:
    notifier = TelegramNotifier()
    return notifier.send_message(text, **kwargs)
