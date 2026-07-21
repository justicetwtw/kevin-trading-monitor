"""Integration tests for the delay-resilient us_open runner (Issue #13).

The heavy data stack and Telegram transport are stubbed; the attempt clock is
frozen. These prove the end-to-end delivery contract: claim-before-send,
at-most-once, honest late/recovery copy, fail-closed exit codes, ambiguity
surfacing, runtime regeneration and public-state privacy.
"""

import json
from datetime import datetime

import pytest
import pytz

from src.runners import run_us_open_brief as rub
from src.runners.us_open_sla import resolve_us_open_session
from src.runners.us_open_state import (
    DELIVERY_AMBIGUOUS,
    DELIVERY_CLAIMED,
    DELIVERY_FAILED,
    DELIVERY_SENT,
    DELIVERY_SKIPPED,
    UsOpenDeliveryStore,
    new_record,
)

TAIPEI = pytz.timezone("Asia/Taipei")

_LEGACY_BODY = (
    "<b>🚀 美股開盤 brief</b>\n\nSECRET-BODY-MARKER-123"
    "\n\n<i>下次 brief: 美股盤中</i>"
)


def _tpe(y, mo, d, h, mi=0):
    return TAIPEI.localize(datetime(y, mo, d, h, mi))


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolate state paths, env and stub the heavy generation/transport."""
    state_path = tmp_path / "us_open_delivery_state.json"
    monkeypatch.setattr(rub, "STATE_PATH", state_path)
    monkeypatch.setattr(rub, "LEGACY_DEDUP_PATH", tmp_path / "no_legacy.json")
    monkeypatch.setenv("US_OPEN_SCHEDULE_SOURCE", "cron 32 13 * * 1-5")
    monkeypatch.setenv("GITHUB_RUN_ID", "run-42")
    monkeypatch.setattr(rub, "_generate_body", lambda: _LEGACY_BODY)
    return state_path


def _freeze(monkeypatch, dt):
    monkeypatch.setattr(rub, "_now_taipei", lambda: dt)


def _read(state_path, key="us_open:2026-07-20"):
    data = json.loads(state_path.read_text(encoding="utf-8"))
    return data["sessions"].get(key)


def _preseed(state_path, session, **kw):
    store = UsOpenDeliveryStore(state_path)
    store.upsert(new_record(
        session,
        status=kw.get("status"),
        lateness_minutes=kw.get("lateness", 0),
        schedule_source="prior",
        workflow_run_id="prior",
        workflow_started_at="2026-07-20T21:30:00+08:00",
        delivery_state=kw["delivery_state"],
    ))


# --- happy paths ------------------------------------------------------------

def test_on_time_send_records_sent_and_plain_title(env, monkeypatch):
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 32))  # +2
    captured = []
    monkeypatch.setattr(rub, "_send", lambda m: captured.append(m) or True)

    rc = rub.main()

    assert rc == 0
    rec = _read(env)
    assert rec["delivery_state"] == DELIVERY_SENT
    assert rec["status"] == "on_time"
    assert rec["lateness_minutes"] == 2
    assert rec["sent_at"] is not None
    assert rec["generation_started_at"] is not None
    assert rec["generation_finished_at"] is not None
    assert rec["schedule_source"] == "cron 32 13 * * 1-5"
    assert rec["workflow_run_id"] == "run-42"
    assert rec["expected_at_taipei"].startswith("2026-07-20T21:30")
    assert captured and captured[0].startswith("<b>🚀 美股開盤 brief</b>")
    assert "延遲補發" not in captured[0]


def test_late_send_uses_delayed_title(env, monkeypatch):
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 50))  # +20
    captured = []
    monkeypatch.setattr(rub, "_send", lambda m: captured.append(m) or True)

    rc = rub.main()

    assert rc == 0
    assert _read(env)["status"] == "late"
    assert "延遲補發（晚 20 分鐘）" in captured[0]


def test_intraday_recovery_uses_makeup_title(env, monkeypatch):
    _freeze(monkeypatch, _tpe(2026, 7, 20, 23, 25))  # +115 (the incident)
    captured = []
    monkeypatch.setattr(rub, "_send", lambda m: captured.append(m) or True)

    rc = rub.main()

    assert rc == 0
    assert _read(env)["status"] == "intraday_recovery"
    assert "盤中補發" in captured[0]
    assert "115" in captured[0]


# --- idempotency ------------------------------------------------------------

def test_duplicate_session_does_not_resend(env, monkeypatch):
    _preseed(env, resolve_us_open_session(_tpe(2026, 7, 20, 21, 32)),
             delivery_state=DELIVERY_SENT, status="on_time")
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 39))  # a later watchdog attempt
    send = _NeverCalled()
    monkeypatch.setattr(rub, "_send", send)

    rc = rub.main()

    assert rc == 0
    assert send.called is False


def test_migrated_legacy_session_dedups(env, monkeypatch, tmp_path):
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"2026-07-20": {"us_open": True}}),
                      encoding="utf-8")
    monkeypatch.setattr(rub, "LEGACY_DEDUP_PATH", legacy)
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 32))
    send = _NeverCalled()
    monkeypatch.setattr(rub, "_send", send)

    rc = rub.main()

    assert rc == 0
    assert send.called is False


def test_retry_after_failure_sends(env, monkeypatch):
    _preseed(env, resolve_us_open_session(_tpe(2026, 7, 20, 21, 32)),
             delivery_state=DELIVERY_FAILED, status="on_time")
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 35))  # still in-window
    monkeypatch.setattr(rub, "_send", lambda m: True)

    rc = rub.main()

    assert rc == 0
    assert _read(env)["delivery_state"] == DELIVERY_SENT


# --- skips ------------------------------------------------------------------

def test_expired_records_miss_and_does_not_send(env, monkeypatch):
    _freeze(monkeypatch, _tpe(2026, 7, 21, 4, 30))  # after 04:00 close
    send = _NeverCalled()
    monkeypatch.setattr(rub, "_send", send)

    rc = rub.main()

    assert rc == 0
    assert send.called is False
    rec = _read(env)
    assert rec["status"] == "expired"
    assert rec["delivery_state"] == DELIVERY_SKIPPED
    assert rec["stage_code"] == "schedule_delay"


def test_early_attempt_skips_without_state(env, monkeypatch):
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 0))  # before open
    send = _NeverCalled()
    monkeypatch.setattr(rub, "_send", send)

    rc = rub.main()

    assert rc == 0
    assert send.called is False
    assert not env.exists() or _read(env) is None


def test_weekend_attempt_skips(env, monkeypatch):
    _freeze(monkeypatch, _tpe(2026, 7, 18, 21, 32))  # Saturday
    send = _NeverCalled()
    monkeypatch.setattr(rub, "_send", send)

    rc = rub.main()

    assert rc == 0
    assert send.called is False


# --- failure / ambiguity (fail closed) --------------------------------------

def test_telegram_failure_is_red_and_retryable(env, monkeypatch):
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 32))
    monkeypatch.setattr(rub, "_send", lambda m: False)

    rc = rub.main()

    assert rc == 1
    rec = _read(env)
    assert rec["delivery_state"] == DELIVERY_FAILED
    assert rec["stage_code"] == "telegram_send_failed"


def test_generation_failure_is_red_and_does_not_send(env, monkeypatch):
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 32))

    def _boom():
        raise RuntimeError("data source down")

    monkeypatch.setattr(rub, "_generate_body", _boom)
    send = _NeverCalled()
    monkeypatch.setattr(rub, "_send", send)

    rc = rub.main()

    assert rc == 1
    assert send.called is False
    rec = _read(env)
    assert rec["delivery_state"] == DELIVERY_FAILED
    assert rec["stage_code"] == "generation_failed"


def test_prior_unresolved_claim_surfaces_ambiguous_not_duplicate(env, monkeypatch):
    _preseed(env, resolve_us_open_session(_tpe(2026, 7, 20, 21, 32)),
             delivery_state=DELIVERY_CLAIMED, status="on_time")
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 39))
    send = _NeverCalled()
    monkeypatch.setattr(rub, "_send", send)

    rc = rub.main()

    assert rc == 1
    assert send.called is False
    rec = _read(env)
    assert rec["delivery_state"] == DELIVERY_AMBIGUOUS
    assert rec["stage_code"] == "ambiguous_delivery"


# --- ordering / regeneration / privacy --------------------------------------

def test_claim_is_persisted_before_send(env, monkeypatch):
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 32))
    seen = {}

    def _send_checks_state(_message):
        seen["at_send"] = _read(env)["delivery_state"]
        return True

    monkeypatch.setattr(rub, "_send", _send_checks_state)

    rc = rub.main()

    assert rc == 0
    assert seen["at_send"] == DELIVERY_CLAIMED  # claim on disk before send
    assert _read(env)["delivery_state"] == DELIVERY_SENT


def test_body_is_regenerated_at_execution_time(env, monkeypatch):
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 32))
    calls = {"n": 0}

    def _gen():
        calls["n"] += 1
        return _LEGACY_BODY

    monkeypatch.setattr(rub, "_generate_body", _gen)
    monkeypatch.setattr(rub, "_send", lambda m: True)

    rub.main()

    assert calls["n"] == 1  # regenerated when the workflow actually ran


def test_public_state_leaks_no_message_or_secret(env, monkeypatch):
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 32))
    monkeypatch.setattr(rub, "_send", lambda m: True)

    rub.main()

    blob = env.read_text(encoding="utf-8").lower()
    assert "secret-body-marker-123" not in blob  # Telegram body never persisted
    for forbidden in ("token", "chat_id", "bot", "position"):
        assert forbidden not in blob


class _NeverCalled:
    called = False

    def __call__(self, *_a, **_k):
        self.called = True
        raise AssertionError("send must not be called")
