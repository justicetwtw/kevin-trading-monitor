"""Telegram delivery-completeness and log-redaction regression tests."""

import httpx

from src.alerts import telegram_bot


class _Response:
    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text


class _Client:
    payloads = []
    responses = []
    exception = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json):
        self.payloads.append(json)
        if self.exception is not None:
            raise self.exception
        if self.responses:
            return self.responses.pop(0)
        return _Response()


def _reset():
    _Client.payloads = []
    _Client.responses = []
    _Client.exception = None


def test_sensitive_telegram_message_and_chat_id_are_redacted(monkeypatch):
    _reset()
    monkeypatch.setattr(telegram_bot.httpx, "AsyncClient", _Client)
    logged = []
    monkeypatch.setattr(
        telegram_bot.logger,
        "info",
        lambda message: logged.append(message),
    )
    notifier = telegram_bot.TelegramNotifier(
        token="token",
        chat_ids=["123456789"],
    )

    ok = notifier.send_message(
        "PRIVATE_SYMBOL strike 220 account 999999",
        sensitive=True,
    )

    assert ok is True
    joined = "\n".join(logged)
    assert "sensitive message redacted" in joined
    assert "recipient#1" in joined
    for secret in ("PRIVATE_SYMBOL", "220", "999999", "123456789"):
        assert secret not in joined


def test_nonsensitive_message_keeps_preview_but_not_chat_id(monkeypatch):
    _reset()
    monkeypatch.setattr(telegram_bot.httpx, "AsyncClient", _Client)
    logged = []
    monkeypatch.setattr(
        telegram_bot.logger,
        "info",
        lambda message: logged.append(message),
    )
    notifier = telegram_bot.TelegramNotifier(
        token="token",
        chat_ids=["123456789"],
    )

    ok = notifier.send_message("public market brief", sensitive=False)

    assert ok is True
    joined = "\n".join(logged)
    assert "public market brief" in joined
    assert "123456789" not in joined
    assert _Client.payloads[0]["parse_mode"] == "HTML"


def test_plain_text_message_omits_parse_mode(monkeypatch):
    _reset()
    monkeypatch.setattr(telegram_bot.httpx, "AsyncClient", _Client)
    notifier = telegram_bot.TelegramNotifier(
        token="token",
        chat_ids=["123"],
    )

    ok = notifier.send_message(
        "Literal <tag> & arbitrary Truth Social text",
        parse_mode=None,
    )

    assert ok is True
    assert "parse_mode" not in _Client.payloads[0]
    assert _Client.payloads[0]["text"] == (
        "Literal <tag> & arbitrary Truth Social text"
    )


def test_multi_recipient_send_requires_every_recipient_by_default(monkeypatch):
    _reset()
    _Client.responses = [_Response(200), _Response(500, "failure")]
    monkeypatch.setattr(telegram_bot.httpx, "AsyncClient", _Client)
    notifier = telegram_bot.TelegramNotifier(
        token="token",
        chat_ids=["111", "222"],
    )

    assert notifier.send_message("message") is False
    assert len(_Client.payloads) == 2


def test_require_all_can_be_disabled_explicitly(monkeypatch):
    _reset()
    _Client.responses = [_Response(200), _Response(500, "failure")]
    monkeypatch.setattr(telegram_bot.httpx, "AsyncClient", _Client)
    notifier = telegram_bot.TelegramNotifier(
        token="token",
        chat_ids=["111", "222"],
    )

    assert notifier.send_message("message", require_all=False) is True


def test_transport_error_log_never_contains_token_url_or_chat_id(monkeypatch):
    _reset()
    request = httpx.Request(
        "POST",
        "https://api.telegram.org/botSUPER_SECRET_TOKEN/sendMessage",
    )
    _Client.exception = httpx.ConnectError("network failure", request=request)
    monkeypatch.setattr(telegram_bot.httpx, "AsyncClient", _Client)
    logged = []
    monkeypatch.setattr(
        telegram_bot.logger,
        "error",
        lambda message: logged.append(message),
    )
    notifier = telegram_bot.TelegramNotifier(
        token="SUPER_SECRET_TOKEN",
        chat_ids=["987654321"],
    )

    assert notifier.send_message("message") is False
    joined = "\n".join(logged)
    assert "ConnectError" in joined
    assert "recipient#1" in joined
    assert "SUPER_SECRET_TOKEN" not in joined
    assert "987654321" not in joined
    assert "api.telegram.org" not in joined
