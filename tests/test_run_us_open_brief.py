"""Integration tests for the delay-resilient us_open runner (Issue #13).

The heavy data stack and Telegram transport are stubbed; the attempt clock is
frozen. These prove: claim-durably-before-send, at-most-once, honest phase-aware
copy, tri-state send handling (sent/failed/ambiguous), fail-closed exit codes,
expired-miss red, ambiguity surfacing, corrupt-state fail-closed, real
workflow-start timestamp, runtime regeneration and public-state privacy.
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
    DELIVERY_OBSERVING,
    DELIVERY_SENT,
    DELIVERY_SKIPPED,
    UsOpenDeliveryStore,
    new_record,
)

TAIPEI = pytz.timezone("Asia/Taipei")

_BODY_MARKER = "SECRET-BODY-MARKER-123"
_LEGACY_BODY = (
    f"<b>🚀 美股開盤 brief</b>\n\n{_BODY_MARKER}"
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
    monkeypatch.delenv("US_OPEN_WORKFLOW_STARTED_AT", raising=False)
    monkeypatch.setattr(rub, "_generate_body", lambda bt: _LEGACY_BODY)
    # Durable push is a CI-only git op; default to the disabled (local) no-op.
    monkeypatch.setattr(rub, "_durable_push", lambda msg: rub.PUSH_DISABLED)
    return state_path


def _freeze(monkeypatch, dt):
    monkeypatch.setattr(rub, "_now_taipei", lambda: dt)


def _stepped_clock(monkeypatch, early, late, switch_after=4):
    """Advance the runner clock from `early` to `late` after N _now calls.

    The first `switch_after` calls (runner start, gen recompute, gen timestamps)
    return `early`; the send recompute / sent_at / telemetry return `late`.
    """
    calls = {"n": 0}

    def _now():
        calls["n"] += 1
        return early if calls["n"] <= switch_after else late

    monkeypatch.setattr(rub, "_now_taipei", _now)


def _sender(outcome, delivered=1, total=1, sink=None):
    def _send(message):
        if sink is not None:
            sink.append(message)
        return {"outcome": outcome, "delivered": delivered, "total": total}

    return _send


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


class _NeverCalled:
    called = False

    def __call__(self, *_a, **_k):
        self.called = True
        raise AssertionError("send must not be called")


# --- happy paths ------------------------------------------------------------

def test_on_time_send_records_sent_and_plain_title(env, monkeypatch):
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 32))  # +2
    monkeypatch.setenv("US_OPEN_WORKFLOW_STARTED_AT", "2026-07-20T13:31:00Z")
    captured = []
    monkeypatch.setattr(rub, "_send_detailed", _sender("sent", sink=captured))

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
    # real workflow-start (before setup) is recorded, separate from runner start.
    assert rec["workflow_started_at"] == "2026-07-20T13:31:00Z"
    assert rec["runner_started_at"] is not None
    assert rec["expected_at_taipei"].startswith("2026-07-20T21:30")
    assert captured and captured[0].startswith("<b>🚀 美股開盤 brief</b>")
    assert "延遲補發" not in captured[0]


def test_late_send_uses_delayed_title_and_us_open_body(env, monkeypatch):
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 50))  # +20
    captured = []
    body_types = []
    monkeypatch.setattr(rub, "_generate_body",
                        lambda bt: body_types.append(bt) or _LEGACY_BODY)
    monkeypatch.setattr(rub, "_send_detailed", _sender("sent", sink=captured))

    rc = rub.main()

    assert rc == 0
    assert _read(env)["status"] == "late"
    assert "延遲補發（晚 20 分鐘）" in captured[0]
    assert body_types == ["us_open"]  # still near the open


def test_intraday_recovery_uses_midday_body_and_makeup_title(env, monkeypatch):
    _freeze(monkeypatch, _tpe(2026, 7, 20, 23, 25))  # +115 (the incident)
    captured = []
    body_types = []
    monkeypatch.setattr(rub, "_generate_body",
                        lambda bt: body_types.append(bt) or _LEGACY_BODY)
    monkeypatch.setattr(rub, "_send_detailed", _sender("sent", sink=captured))

    rc = rub.main()

    assert rc == 0
    assert _read(env)["status"] == "intraday_recovery"
    assert "盤中補發" in captured[0]
    assert "115" in captured[0]
    # phase-appropriate body: intraday, NOT the premarket/open template.
    assert body_types == ["us_midday"]


# --- idempotency ------------------------------------------------------------

def test_duplicate_session_does_not_resend(env, monkeypatch):
    _preseed(env, resolve_us_open_session(_tpe(2026, 7, 20, 21, 32)),
             delivery_state=DELIVERY_SENT, status="on_time")
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 39))
    monkeypatch.setattr(rub, "_send_detailed", _NeverCalled())

    rc = rub.main()

    assert rc == 0
    assert _read(env)["delivery_state"] == DELIVERY_SENT


def test_migrated_legacy_session_dedups(env, monkeypatch, tmp_path):
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"2026-07-20": {"us_open": True}}),
                      encoding="utf-8")
    monkeypatch.setattr(rub, "LEGACY_DEDUP_PATH", legacy)
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 32))
    monkeypatch.setattr(rub, "_send_detailed", _NeverCalled())

    rc = rub.main()

    assert rc == 0


def test_retry_after_definitive_failure_sends(env, monkeypatch):
    _preseed(env, resolve_us_open_session(_tpe(2026, 7, 20, 21, 32)),
             delivery_state=DELIVERY_FAILED, status="on_time")
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 35))
    monkeypatch.setattr(rub, "_send_detailed", _sender("sent"))

    rc = rub.main()

    assert rc == 0
    assert _read(env)["delivery_state"] == DELIVERY_SENT


# --- skips ------------------------------------------------------------------

def test_expired_miss_is_red_and_records_miss(env, monkeypatch):
    _freeze(monkeypatch, _tpe(2026, 7, 21, 4, 30))  # after 04:00 close
    monkeypatch.setattr(rub, "_send_detailed", _NeverCalled())

    rc = rub.main()

    assert rc == 1  # a completely missed opening brief must not be green
    rec = _read(env)
    assert rec["status"] == "expired"
    assert rec["delivery_state"] == DELIVERY_SKIPPED
    assert rec["stage_code"] == "schedule_delay"


def test_expired_after_failure_preserves_failure_signal(env, monkeypatch):
    _preseed(env, resolve_us_open_session(_tpe(2026, 7, 20, 21, 32)),
             delivery_state=DELIVERY_FAILED, status="late")
    # bump the prior record's stage_code as the runner would have
    store = UsOpenDeliveryStore(env)
    rec = store.get("us_open:2026-07-20")
    rec["stage_code"] = "telegram_send_failed"
    store.upsert(rec)
    _freeze(monkeypatch, _tpe(2026, 7, 21, 4, 30))
    monkeypatch.setattr(rub, "_send_detailed", _NeverCalled())

    rc = rub.main()

    assert rc == 1
    rec = _read(env)
    assert rec["delivery_state"] == DELIVERY_FAILED  # not downgraded to skipped
    assert rec["stage_code"] == "telegram_send_failed"  # failure preserved
    assert rec["status"] == "expired"


def test_early_attempt_records_observing_without_send(env, monkeypatch):
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 0))  # before open
    monkeypatch.setattr(rub, "_send_detailed", _NeverCalled())

    rc = rub.main()

    assert rc == 0
    rec = _read(env)
    assert rec["delivery_state"] == DELIVERY_OBSERVING  # durable telemetry
    assert rec["observed_attempts"][-1]["outcome"] == "early"


def test_weekend_attempt_skips(env, monkeypatch):
    _freeze(monkeypatch, _tpe(2026, 7, 18, 21, 32))  # Saturday
    monkeypatch.setattr(rub, "_send_detailed", _NeverCalled())

    rc = rub.main()

    assert rc == 0
    assert not env.exists() or _read(env) is None


# --- failure / ambiguity (fail closed) --------------------------------------

def test_definitive_send_failure_is_red_and_retryable(env, monkeypatch):
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 32))
    monkeypatch.setattr(rub, "_send_detailed", _sender("failed", delivered=0))

    rc = rub.main()

    assert rc == 1
    rec = _read(env)
    assert rec["delivery_state"] == DELIVERY_FAILED
    assert rec["stage_code"] == "telegram_send_failed"


def test_ambiguous_send_is_red_and_not_retryable(env, monkeypatch):
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 32))
    monkeypatch.setattr(rub, "_send_detailed",
                        _sender("ambiguous", delivered=0, total=2))

    rc = rub.main()

    assert rc == 1
    rec = _read(env)
    assert rec["delivery_state"] == DELIVERY_AMBIGUOUS
    assert rec["stage_code"] == "ambiguous_delivery"


def test_generation_failure_is_red_and_does_not_send(env, monkeypatch):
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 32))

    def _boom(_bt):
        raise RuntimeError("data source down")

    monkeypatch.setattr(rub, "_generate_body", _boom)
    monkeypatch.setattr(rub, "_send_detailed", _NeverCalled())

    rc = rub.main()

    assert rc == 1
    rec = _read(env)
    assert rec["delivery_state"] == DELIVERY_FAILED
    assert rec["stage_code"] == "generation_failed"


def test_prior_unresolved_claim_surfaces_ambiguous_not_duplicate(env, monkeypatch):
    _preseed(env, resolve_us_open_session(_tpe(2026, 7, 20, 21, 32)),
             delivery_state=DELIVERY_CLAIMED, status="on_time")
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 39))
    monkeypatch.setattr(rub, "_send_detailed", _NeverCalled())

    rc = rub.main()

    assert rc == 1
    rec = _read(env)
    assert rec["delivery_state"] == DELIVERY_AMBIGUOUS
    assert rec["stage_code"] == "ambiguous_delivery"


def test_already_ambiguous_stays_red_and_does_not_resend(env, monkeypatch):
    _preseed(env, resolve_us_open_session(_tpe(2026, 7, 20, 21, 32)),
             delivery_state=DELIVERY_AMBIGUOUS, status="on_time")
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 39))
    monkeypatch.setattr(rub, "_send_detailed", _NeverCalled())

    rc = rub.main()

    assert rc == 1  # not green while delivery is in doubt (contract section 6)
    assert _read(env)["delivery_state"] == DELIVERY_AMBIGUOUS


def test_corrupt_state_fails_closed_without_sending(env, monkeypatch):
    env.write_text("{not valid json", encoding="utf-8")
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 32))
    monkeypatch.setattr(rub, "_send_detailed", _NeverCalled())

    rc = rub.main()

    assert rc == 1  # corrupt state must not be treated as empty / license a send
    # the corrupt file is not silently rewritten as empty
    assert env.read_text(encoding="utf-8") == "{not valid json"


def test_structurally_corrupt_sessions_fails_closed(env, monkeypatch):
    # Parseable JSON but a wrong-typed `sessions` must not be read as empty.
    env.write_text('{"schema_version": 1, "sessions": []}', encoding="utf-8")
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 32))
    monkeypatch.setattr(rub, "_send_detailed", _NeverCalled())

    rc = rub.main()

    assert rc == 1
    assert env.read_text(encoding="utf-8") == '{"schema_version": 1, "sessions": []}'


def test_durable_claim_push_failure_is_red_and_does_not_send(env, monkeypatch):
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 32))
    monkeypatch.setattr(rub, "_durable_push", lambda msg: rub.PUSH_FAILED)
    monkeypatch.setattr(rub, "_send_detailed", _NeverCalled())

    rc = rub.main()

    assert rc == 1  # a claim that isn't durable must not send (dup risk)
    rec = _read(env)
    assert rec["delivery_state"] == DELIVERY_FAILED
    assert rec["stage_code"] == "claim_persist_failed"


# --- ordering / durability / regeneration / privacy -------------------------

def test_claim_is_durably_pushed_before_send(env, monkeypatch):
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 32))
    order = []
    monkeypatch.setattr(rub, "_durable_push",
                        lambda msg: order.append(("push", msg)) or True)

    def _send(_message):
        order.append(("send", _read(env)["delivery_state"]))
        return {"outcome": "sent", "delivered": 1, "total": 1}

    monkeypatch.setattr(rub, "_send_detailed", _send)

    rc = rub.main()

    assert rc == 0
    assert order[0][0] == "push"       # claim pushed first
    assert "us_open claim" in order[0][1]
    assert order[1] == ("send", DELIVERY_CLAIMED)  # claim durable at send time
    assert _read(env)["delivery_state"] == DELIVERY_SENT


def test_body_is_regenerated_at_execution_time(env, monkeypatch):
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 32))
    calls = {"n": 0}

    def _gen(_bt):
        calls["n"] += 1
        return _LEGACY_BODY

    monkeypatch.setattr(rub, "_generate_body", _gen)
    monkeypatch.setattr(rub, "_send_detailed", _sender("sent"))

    rub.main()

    assert calls["n"] == 1


def test_advancing_clock_crosses_on_time_to_late_at_send(env, monkeypatch):
    # starts at +9 (on_time) but the send lands at +11 (late).
    _stepped_clock(monkeypatch, _tpe(2026, 7, 20, 21, 39), _tpe(2026, 7, 20, 21, 41))
    captured = []
    monkeypatch.setattr(rub, "_send_detailed", _sender("sent", sink=captured))

    rc = rub.main()

    assert rc == 0
    rec = _read(env)
    assert rec["status"] == "late"  # decided at delivery time, not runner start
    assert rec["lateness_minutes"] == 11
    assert "延遲補發（晚 11 分鐘）" in captured[0]


def test_advancing_clock_crosses_late_to_recovery_regenerates_body(env, monkeypatch):
    # starts at +29 (late, us_open body) but crosses +30 to intraday_recovery.
    _stepped_clock(monkeypatch, _tpe(2026, 7, 20, 21, 59), _tpe(2026, 7, 20, 22, 1))
    captured = []
    body_types = []
    monkeypatch.setattr(rub, "_generate_body",
                        lambda bt: body_types.append(bt) or _LEGACY_BODY)
    monkeypatch.setattr(rub, "_send_detailed", _sender("sent", sink=captured))

    rc = rub.main()

    assert rc == 0
    assert _read(env)["status"] == "intraday_recovery"
    assert "盤中補發" in captured[0]
    # the body was regenerated with the intraday template at the new phase.
    assert body_types == ["us_open", "us_midday"]


def test_terminal_outcome_is_durably_pushed(env, monkeypatch):
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 32))
    pushes = []
    monkeypatch.setattr(rub, "_durable_push",
                        lambda msg: pushes.append(msg) or rub.PUSH_OK)
    monkeypatch.setattr(rub, "_send_detailed", _sender("sent"))

    rub.main()

    assert len(pushes) == 2  # claim, then the terminal result
    assert "claim" in pushes[0] and "sent" in pushes[1]


def test_terminal_persist_failure_is_red_even_when_delivered(env, monkeypatch):
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 32))
    calls = {"n": 0}

    def _push(_msg):
        calls["n"] += 1
        return rub.PUSH_OK if calls["n"] == 1 else rub.PUSH_FAILED  # claim ok, result fails

    monkeypatch.setattr(rub, "_durable_push", _push)
    monkeypatch.setattr(rub, "_send_detailed", _sender("sent"))

    rc = rub.main()

    assert rc == 1  # delivered, but the final state isn't durable -> surface red
    rec = _read(env)
    assert rec["delivery_state"] == DELIVERY_SENT
    assert any(a["outcome"] == "state_persist_failed"
               for a in rec["observed_attempts"])


def test_malformed_record_fails_closed_without_sending(env, monkeypatch):
    env.write_text('{"sessions": {"us_open:2026-07-20": []}}', encoding="utf-8")
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 32))
    monkeypatch.setattr(rub, "_send_detailed", _NeverCalled())

    rc = rub.main()

    assert rc == 1  # a malformed record must not crash into a send


def test_telemetry_carries_forward_early_then_send(env, monkeypatch):
    # 1) an early (pre-open) attempt records durable observing telemetry
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 0))
    monkeypatch.setattr(rub, "_send_detailed", _sender("sent"))
    rub.main()
    assert _read(env)["delivery_state"] == DELIVERY_OBSERVING

    # 2) the on-time send must not erase the earlier attempt from history
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 32))
    rub.main()

    rec = _read(env)
    assert rec["delivery_state"] == DELIVERY_SENT
    outcomes = [a["outcome"] for a in rec["observed_attempts"]]
    assert "early" in outcomes and "sent" in outcomes
    # every entry is independently attributable with public-safe fields
    for a in rec["observed_attempts"]:
        assert "at" in a and "workflow_run_id" in a and "schedule_source" in a


def test_telemetry_carries_forward_failed_then_sent(env, monkeypatch):
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 32))
    monkeypatch.setattr(rub, "_send_detailed", _sender("failed", delivered=0))
    rub.main()
    assert _read(env)["delivery_state"] == DELIVERY_FAILED

    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 35))
    monkeypatch.setattr(rub, "_send_detailed", _sender("sent"))
    rub.main()

    rec = _read(env)
    assert rec["delivery_state"] == DELIVERY_SENT
    outcomes = [a["outcome"] for a in rec["observed_attempts"]]
    assert "send_failed" in outcomes and "sent" in outcomes  # failure stays visible


def test_public_state_leaks_no_message_or_secret(env, monkeypatch):
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 32))
    monkeypatch.setattr(rub, "_send_detailed", _sender("sent"))

    rub.main()

    blob = env.read_text(encoding="utf-8").lower()
    assert _BODY_MARKER.lower() not in blob  # Telegram body never persisted
    for forbidden in ("token", "chat_id", "bot", "position"):
        assert forbidden not in blob
