"""Telegram connectivity, multi-recipient and settings tests."""

import importlib
import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.alerts.telegram_bot import TelegramNotifier


def _patch_httpx(post_side_effect=None, post_status_code=200, post_text=""):
    mock_client = MagicMock()
    if post_side_effect is not None:
        mock_client.post = AsyncMock(side_effect=post_side_effect)
    else:
        mock_resp = MagicMock()
        mock_resp.status_code = post_status_code
        mock_resp.text = post_text
        mock_client.post = AsyncMock(return_value=mock_resp)

    mock_async_client = MagicMock()
    mock_async_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_async_client.__aexit__ = AsyncMock(return_value=None)
    patcher = patch(
        "src.alerts.telegram_bot.httpx.AsyncClient",
        return_value=mock_async_client,
    )
    return patcher, mock_client


def test_token_and_chat_id_required():
    with pytest.raises(ValueError):
        TelegramNotifier(token="", chat_ids=[])


def test_legacy_chat_id_single_value_still_works():
    notifier = TelegramNotifier(token="t", chat_id="123")
    assert notifier.chat_ids == ["123"]


def test_chat_ids_list_param():
    notifier = TelegramNotifier(token="t", chat_ids=["123", "456"])
    assert notifier.chat_ids == ["123", "456"]


def test_chat_ids_string_coerced_to_list():
    notifier = TelegramNotifier(token="t", chat_ids="789")
    assert notifier.chat_ids == ["789"]


def test_send_to_multi_chat_ids_all_success():
    patcher, mock_client = _patch_httpx(post_status_code=200)
    with patcher:
        notifier = TelegramNotifier(token="t", chat_ids=["111", "222"])
        ok = notifier.send_message("hi")
    assert ok is True
    assert mock_client.post.await_count == 2
    sent_chat_ids = [
        call.kwargs["json"]["chat_id"]
        for call in mock_client.post.await_args_list
    ]
    assert sent_chat_ids == ["111", "222"]


def test_detailed_all_200_is_sent():
    patcher, _ = _patch_httpx(post_status_code=200)
    with patcher:
        notifier = TelegramNotifier(token="t", chat_ids=["111", "222"])
        result = notifier.send_message_detailed("hi")
    assert result["outcome"] == "sent"
    assert result["delivered"] == 2


def test_detailed_all_rejected_is_failed_retryable():
    """A definitive HTTP rejection means not delivered — safe to retry."""
    patcher, _ = _patch_httpx(post_status_code=400)
    with patcher:
        notifier = TelegramNotifier(token="t", chat_ids=["111"])
        result = notifier.send_message_detailed("hi")
    assert result["outcome"] == "failed"
    assert result["delivered"] == 0


def test_detailed_timeout_is_ambiguous():
    """A transport/timeout error may have reached Telegram: ambiguous, no retry."""
    async def boom(*_, **__):
        raise httpx.TimeoutException("timeout")

    patcher, _ = _patch_httpx(post_side_effect=boom)
    with patcher:
        notifier = TelegramNotifier(token="t", chat_ids=["111"])
        result = notifier.send_message_detailed("hi")
    assert result["outcome"] == "ambiguous"


def test_detailed_partial_delivery_is_ambiguous():
    """Some recipients delivered, others rejected: ambiguous (message went out)."""
    responses = [
        MagicMock(status_code=200, text="ok"),
        MagicMock(status_code=400, text="bad"),
    ]

    async def side_effect(*_, **__):
        return responses.pop(0)

    patcher, _ = _patch_httpx(post_side_effect=side_effect)
    with patcher:
        notifier = TelegramNotifier(token="t", chat_ids=["111", "222"])
        result = notifier.send_message_detailed("hi")
    assert result["outcome"] == "ambiguous"
    assert result["delivered"] == 1


def test_partial_failure_returns_false_by_default():
    """A message is not fully delivered when any configured recipient fails."""
    responses = [
        MagicMock(status_code=401, text="unauth"),
        MagicMock(status_code=200, text="ok"),
    ]

    async def side_effect(*_, **__):
        return responses.pop(0)

    patcher, mock_client = _patch_httpx(post_side_effect=side_effect)
    with patcher:
        notifier = TelegramNotifier(token="t", chat_ids=["111", "222"])
        ok = notifier.send_message("hi")
    assert ok is False
    assert mock_client.post.await_count == 2


def test_partial_failure_can_use_legacy_any_semantics_explicitly():
    responses = [
        MagicMock(status_code=401, text="unauth"),
        MagicMock(status_code=200, text="ok"),
    ]

    async def side_effect(*_, **__):
        return responses.pop(0)

    patcher, _ = _patch_httpx(post_side_effect=side_effect)
    with patcher:
        notifier = TelegramNotifier(token="t", chat_ids=["111", "222"])
        ok = notifier.send_message("hi", require_all=False)
    assert ok is True


def test_all_failure_returns_false_on_timeout():
    patcher, mock_client = _patch_httpx(
        post_side_effect=httpx.TimeoutException("timed out"),
    )
    with patcher:
        notifier = TelegramNotifier(token="t", chat_ids=["111", "222"])
        ok = notifier.send_message("hi")
    assert ok is False
    assert mock_client.post.await_count == 2


def test_all_failure_returns_false_on_http_error():
    patcher, _ = _patch_httpx(post_status_code=500, post_text="boom")
    with patcher:
        notifier = TelegramNotifier(token="t", chat_ids=["111", "222"])
        ok = notifier.send_message("hi")
    assert ok is False


def test_send_to_single_chat_id_legacy():
    patcher, mock_client = _patch_httpx(post_status_code=200)
    with patcher:
        notifier = TelegramNotifier(token="t", chat_id="999")
        ok = notifier.send_message("hi")
    assert ok is True
    assert mock_client.post.await_count == 1
    assert mock_client.post.await_args.kwargs["json"]["chat_id"] == "999"


def test_payload_includes_text_and_parse_mode():
    patcher, mock_client = _patch_httpx(post_status_code=200)
    with patcher:
        notifier = TelegramNotifier(token="t", chat_ids=["111"])
        notifier.send_message("<b>hello</b>", parse_mode="HTML")
    payload = mock_client.post.await_args.kwargs["json"]
    assert payload["text"] == "<b>hello</b>"
    assert payload["parse_mode"] == "HTML"


def test_settings_parses_comma_separated(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123,456,789")
    import src.config.settings as settings_mod

    importlib.reload(settings_mod)
    try:
        assert settings_mod.TELEGRAM_CHAT_IDS == ["123", "456", "789"]
        assert settings_mod.TELEGRAM_CHAT_ID == "123"
    finally:
        importlib.reload(settings_mod)


def test_settings_handles_whitespace(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", " 123 , 456 ")
    import src.config.settings as settings_mod

    importlib.reload(settings_mod)
    try:
        assert settings_mod.TELEGRAM_CHAT_IDS == ["123", "456"]
    finally:
        importlib.reload(settings_mod)


def test_settings_empty_returns_empty_list(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "")
    import src.config.settings as settings_mod

    importlib.reload(settings_mod)
    try:
        assert settings_mod.TELEGRAM_CHAT_IDS == []
        assert settings_mod.TELEGRAM_CHAT_ID == ""
    finally:
        importlib.reload(settings_mod)


def test_settings_single_value_still_works(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654321")
    import src.config.settings as settings_mod

    importlib.reload(settings_mod)
    try:
        assert settings_mod.TELEGRAM_CHAT_IDS == ["987654321"]
        assert settings_mod.TELEGRAM_CHAT_ID == "987654321"
    finally:
        importlib.reload(settings_mod)


@pytest.mark.skipif(
    not os.getenv("TELEGRAM_BOT_TOKEN") or not os.getenv("TELEGRAM_CHAT_ID"),
    reason="TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not configured",
)
def test_send_message_live():
    notifier = TelegramNotifier()
    result = notifier.send_message(
        "🧪 <b>pytest test_send_message_live</b>\n\nFrom unit tests."
    )
    assert result is True
