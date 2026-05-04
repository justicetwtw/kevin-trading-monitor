"""Telegram 連線測試 + 多 chat_id 行為測試(Phase 2.5.7)。

Phase 2.5.7 hotfix:改用 httpx 直接打 API,測試也改 patch httpx.AsyncClient。
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.alerts.telegram_bot import TelegramNotifier


def _patch_httpx(post_side_effect=None, post_status_code=200, post_text=""):
    """產生 patcher → src.alerts.telegram_bot.httpx.AsyncClient。

    使用方式:
        with _patch_httpx(...) as mock_post:
            ...
    回傳的 mock 是 client.post(AsyncMock),可檢查 await_args_list。
    """
    mock_client = MagicMock()

    if post_side_effect is not None:
        mock_client.post = AsyncMock(side_effect=post_side_effect)
    else:
        mock_resp = MagicMock()
        mock_resp.status_code = post_status_code
        mock_resp.text = post_text
        mock_client.post = AsyncMock(return_value=mock_resp)

    # AsyncClient() context manager
    mock_async_client = MagicMock()
    mock_async_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_async_client.__aexit__ = AsyncMock(return_value=None)

    patcher = patch("src.alerts.telegram_bot.httpx.AsyncClient",
                    return_value=mock_async_client)
    return patcher, mock_client


# ------------------------------------------------------------
# 基本驗證
# ------------------------------------------------------------

def test_token_and_chat_id_required():
    """缺 token 或 chat_id 應該丟 ValueError。"""
    with pytest.raises(ValueError):
        TelegramNotifier(token="", chat_ids=[])


def test_legacy_chat_id_single_value_still_works():
    """舊式 chat_id 單值參數仍可建構(相容性)。"""
    n = TelegramNotifier(token="t", chat_id="123")
    assert n.chat_ids == ["123"]


def test_chat_ids_list_param():
    n = TelegramNotifier(token="t", chat_ids=["123", "456"])
    assert n.chat_ids == ["123", "456"]


def test_chat_ids_string_coerced_to_list():
    """chat_ids 傳 str 會被包成 list。"""
    n = TelegramNotifier(token="t", chat_ids="789")
    assert n.chat_ids == ["789"]


# ------------------------------------------------------------
# 多 chat_id 推送行為
# ------------------------------------------------------------

def test_send_to_multi_chat_ids_all_success():
    """兩個 chat_id 都成功 → POST 被呼叫兩次,回 True。"""
    patcher, mock_client = _patch_httpx(post_status_code=200)
    with patcher:
        n = TelegramNotifier(token="t", chat_ids=["111", "222"])
        ok = n.send_message("hi")
    assert ok is True
    assert mock_client.post.await_count == 2
    sent_chat_ids = [
        c.kwargs["json"]["chat_id"] for c in mock_client.post.await_args_list
    ]
    assert sent_chat_ids == ["111", "222"]


def test_partial_failure_returns_true():
    """一個 401、一個 200 → any 仍 True。"""
    responses = [MagicMock(status_code=401, text="unauth"),
                 MagicMock(status_code=200, text="ok")]

    async def side_effect(*_, **__):
        return responses.pop(0)

    patcher, mock_client = _patch_httpx(post_side_effect=side_effect)
    with patcher:
        n = TelegramNotifier(token="t", chat_ids=["111", "222"])
        ok = n.send_message("hi")
    assert ok is True
    assert mock_client.post.await_count == 2


def test_all_failure_returns_false_on_timeout():
    """全部 chat_id 都 timeout → 回 False。"""
    patcher, mock_client = _patch_httpx(
        post_side_effect=httpx.TimeoutException("timed out"),
    )
    with patcher:
        n = TelegramNotifier(token="t", chat_ids=["111", "222"])
        ok = n.send_message("hi")
    assert ok is False
    assert mock_client.post.await_count == 2


def test_all_failure_returns_false_on_http_error():
    """全部回非 200 → 回 False。"""
    patcher, mock_client = _patch_httpx(post_status_code=500, post_text="boom")
    with patcher:
        n = TelegramNotifier(token="t", chat_ids=["111", "222"])
        ok = n.send_message("hi")
    assert ok is False


def test_send_to_single_chat_id_legacy():
    """舊版單一 chat_id 路徑(向後相容)。"""
    patcher, mock_client = _patch_httpx(post_status_code=200)
    with patcher:
        n = TelegramNotifier(token="t", chat_id="999")
        ok = n.send_message("hi")
    assert ok is True
    assert mock_client.post.await_count == 1
    assert mock_client.post.await_args.kwargs["json"]["chat_id"] == "999"


def test_payload_includes_text_and_parse_mode():
    """送出 payload 應有 text + parse_mode。"""
    patcher, mock_client = _patch_httpx(post_status_code=200)
    with patcher:
        n = TelegramNotifier(token="t", chat_ids=["111"])
        n.send_message("<b>hello</b>", parse_mode="HTML")
    payload = mock_client.post.await_args.kwargs["json"]
    assert payload["text"] == "<b>hello</b>"
    assert payload["parse_mode"] == "HTML"


# ------------------------------------------------------------
# settings.py 解析
# ------------------------------------------------------------

def test_settings_parses_comma_separated(monkeypatch):
    """TELEGRAM_CHAT_ID="123,456" → TELEGRAM_CHAT_IDS=["123","456"]。"""
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123,456,789")
    import importlib

    import src.config.settings as settings_mod
    importlib.reload(settings_mod)
    try:
        assert settings_mod.TELEGRAM_CHAT_IDS == ["123", "456", "789"]
        assert settings_mod.TELEGRAM_CHAT_ID == "123"
    finally:
        importlib.reload(settings_mod)


def test_settings_handles_whitespace(monkeypatch):
    """逗號間有空白也能正確解析。"""
    monkeypatch.setenv("TELEGRAM_CHAT_ID", " 123 , 456 ")
    import importlib

    import src.config.settings as settings_mod
    importlib.reload(settings_mod)
    try:
        assert settings_mod.TELEGRAM_CHAT_IDS == ["123", "456"]
    finally:
        importlib.reload(settings_mod)


def test_settings_empty_returns_empty_list(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "")
    import importlib

    import src.config.settings as settings_mod
    importlib.reload(settings_mod)
    try:
        assert settings_mod.TELEGRAM_CHAT_IDS == []
        assert settings_mod.TELEGRAM_CHAT_ID == ""
    finally:
        importlib.reload(settings_mod)


def test_settings_single_value_still_works(monkeypatch):
    """單一 chat_id(無逗號)→ list 仍只有 1 項。"""
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654321")
    import importlib

    import src.config.settings as settings_mod
    importlib.reload(settings_mod)
    try:
        assert settings_mod.TELEGRAM_CHAT_IDS == ["987654321"]
        assert settings_mod.TELEGRAM_CHAT_ID == "987654321"
    finally:
        importlib.reload(settings_mod)


# ------------------------------------------------------------
# 實連測試(GitHub Secrets 驅動)
# ------------------------------------------------------------

@pytest.mark.skipif(
    not os.getenv("TELEGRAM_BOT_TOKEN") or not os.getenv("TELEGRAM_CHAT_ID"),
    reason="TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 未設定 - 跳過實連測試",
)
def test_send_message_live():
    """實際發送一則測試訊息(需 GitHub Secrets 設定)。"""
    notifier = TelegramNotifier()
    result = notifier.send_message(
        "🧪 <b>pytest test_send_message_live</b>\n\n從單元測試發出。"
    )
    assert result is True
