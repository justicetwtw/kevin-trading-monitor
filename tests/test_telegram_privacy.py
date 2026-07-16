"""Telegram sensitive logging and plain-text payload regression tests."""

from src.alerts import telegram_bot


class _Response:
    status_code = 200
    text = "ok"


class _Client:
    payloads = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json):
        self.payloads.append(json)
        return _Response()


def test_sensitive_telegram_message_is_redacted_from_logs(monkeypatch):
    _Client.payloads = []
    monkeypatch.setattr(telegram_bot.httpx, "AsyncClient", _Client)
    logged = []
    monkeypatch.setattr(
        telegram_bot.logger,
        "info",
        lambda message: logged.append(message),
    )
    notifier = telegram_bot.TelegramNotifier(
        token="token",
        chat_ids=["123"],
    )

    ok = notifier.send_message(
        "PRIVATE_SYMBOL strike 220 account 999999",
        sensitive=True,
    )

    assert ok is True
    joined = "\n".join(logged)
    assert "sensitive message redacted" in joined
    assert "PRIVATE_SYMBOL" not in joined
    assert "220" not in joined
    assert "999999" not in joined


def test_nonsensitive_telegram_message_keeps_preview(monkeypatch):
    _Client.payloads = []
    monkeypatch.setattr(telegram_bot.httpx, "AsyncClient", _Client)
    logged = []
    monkeypatch.setattr(
        telegram_bot.logger,
        "info",
        lambda message: logged.append(message),
    )
    notifier = telegram_bot.TelegramNotifier(
        token="token",
        chat_ids=["123"],
    )

    ok = notifier.send_message("public market brief", sensitive=False)

    assert ok is True
    assert "public market brief" in "\n".join(logged)
    assert _Client.payloads[0]["parse_mode"] == "HTML"


def test_plain_text_message_omits_parse_mode(monkeypatch):
    _Client.payloads = []
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
