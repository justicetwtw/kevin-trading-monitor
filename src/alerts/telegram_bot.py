"""Telegram Bot wrapper with reliable multi-chat delivery and safe logging."""

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
        require_all: bool = True,
    ) -> bool:
        """Send to configured recipients without leaking credentials or chat IDs.

        `parse_mode=None` sends literal plain text. `require_all=True` means a
        multi-recipient send is successful only when every configured recipient
        accepted the message. This prevents one failed recipient from being
        silently treated as delivered.
        """
        url = f"{TELEGRAM_API_BASE}/bot{self.token}/sendMessage"
        results: list[bool] = []
        async with httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT_SEC
        ) as client:
            for index, chat_id in enumerate(self.chat_ids, start=1):
                destination = f"recipient#{index}"
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
                            f"Telegram sent to {destination}: {preview}"
                        )
                        results.append(True)
                    else:
                        # Do not log response bodies: Telegram errors may echo
                        # request details, and Actions logs are public.
                        logger.error(
                            f"Telegram failed for {destination}: "
                            f"HTTP {response.status_code}"
                        )
                        results.append(False)
                except httpx.HTTPError as exc:
                    # Exception strings may contain the Bot API URL (and token).
                    logger.error(
                        f"Telegram transport failed for {destination}: "
                        f"{type(exc).__name__}"
                    )
                    results.append(False)
                except Exception as exc:
                    logger.error(
                        f"Telegram unexpected failure for {destination}: "
                        f"{type(exc).__name__}"
                    )
                    results.append(False)
        if not results:
            return False
        return all(results) if require_all else any(results)

    def send_message(self, text: str, **kwargs) -> bool:
        return asyncio.run(self.send_message_async(text, **kwargs))

    async def send_message_detailed_async(
        self,
        text: str,
        parse_mode: str | None = "HTML",
        disable_notification: bool = False,
        sensitive: bool = False,
    ) -> dict:
        """Send and return a tri-state outcome for exactly-once callers.

        Returns ``{"outcome": "sent"|"failed"|"ambiguous", "delivered": n,
        "total": m}`` where:

        - ``sent``   — every recipient returned HTTP 200;
        - ``failed`` — no recipient was delivered *and* every failure was a
          definitive HTTP rejection (a response was received), so the message
          certainly did not go out and a retry is safe;
        - ``ambiguous`` — a transport/timeout error occurred (the request may
          have reached Telegram) or delivery was partial across recipients.
          The caller must NOT auto-retry an ambiguous outcome, to avoid a
          duplicate; it should surface ``ambiguous_delivery`` instead.
        """
        url = f"{TELEGRAM_API_BASE}/bot{self.token}/sendMessage"
        delivered = 0
        rejected = 0  # definitive non-2xx responses (certainly not delivered)
        unknown = 0  # transport/timeout errors (delivery status unknown)
        total = len(self.chat_ids)
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SEC) as client:
            for index, chat_id in enumerate(self.chat_ids, start=1):
                destination = f"recipient#{index}"
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
                        logger.info(f"Telegram sent to {destination}: {preview}")
                        delivered += 1
                    else:
                        # A received response means Telegram rejected it; the
                        # message certainly did not go out to this recipient.
                        logger.error(
                            f"Telegram rejected for {destination}: "
                            f"HTTP {response.status_code}"
                        )
                        rejected += 1
                except httpx.HTTPError as exc:
                    # Transport/timeout: the request may already have reached
                    # Telegram, so delivery is unknown, not a definitive failure.
                    logger.error(
                        f"Telegram transport unknown for {destination}: "
                        f"{type(exc).__name__}"
                    )
                    unknown += 1
                except Exception as exc:
                    logger.error(
                        f"Telegram unexpected failure for {destination}: "
                        f"{type(exc).__name__}"
                    )
                    unknown += 1

        if total == 0:
            outcome = "failed"
        elif delivered == total:
            outcome = "sent"
        elif delivered > 0 or unknown > 0:
            # partial delivery, or an unconfirmed transport error: ambiguous.
            outcome = "ambiguous"
        else:
            # every recipient returned a definitive rejection: safe to retry.
            outcome = "failed"
        return {"outcome": outcome, "delivered": delivered, "total": total}

    def send_message_detailed(self, text: str, **kwargs) -> dict:
        return asyncio.run(self.send_message_detailed_async(text, **kwargs))


def send_telegram(text: str, **kwargs) -> bool:
    notifier = TelegramNotifier()
    return notifier.send_message(text, **kwargs)


def send_telegram_detailed(text: str, **kwargs) -> dict:
    """Tri-state send for exactly-once callers. See send_message_detailed_async."""
    notifier = TelegramNotifier()
    return notifier.send_message_detailed(text, **kwargs)
