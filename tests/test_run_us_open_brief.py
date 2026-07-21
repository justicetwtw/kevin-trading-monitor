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
    StateReadError,
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
    monkeypatch.setattr(rub, "_durable_push",
                        lambda msg, **kw: rub.PUSH_DISABLED)
    return state_path


@pytest.fixture
def durable_env(tmp_path, monkeypatch):
    """Like ``env`` but runs the REAL durable-push / hydration against a mocked
    ``_git_run`` (``US_OPEN_DURABLE_STATE=1``), so the compare-and-swap and
    authoritative-hydration git paths are exercised end-to-end via ``main()``.
    """
    state_path = tmp_path / "us_open_delivery_state.json"
    monkeypatch.setattr(rub, "STATE_PATH", state_path)
    monkeypatch.setattr(rub, "LEGACY_DEDUP_PATH", tmp_path / "no_legacy.json")
    monkeypatch.setenv("US_OPEN_SCHEDULE_SOURCE", "cron 32 13 * * 1-5")
    monkeypatch.setenv("GITHUB_RUN_ID", "run-42")
    monkeypatch.setenv("US_OPEN_DURABLE_STATE", "1")
    monkeypatch.delenv("US_OPEN_WORKFLOW_STARTED_AT", raising=False)
    monkeypatch.setattr(rub, "_generate_body", lambda bt: _LEGACY_BODY)
    monkeypatch.setattr(rub, "_sleep", lambda s: None)
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
    monkeypatch.setattr(rub, "_durable_push", lambda msg, **kw: rub.PUSH_FAILED)
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
                        lambda msg, **kw: order.append(("push", msg)) or True)

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
                        lambda msg, **kw: pushes.append(msg) or rub.PUSH_OK)
    monkeypatch.setattr(rub, "_send_detailed", _sender("sent"))

    rub.main()

    assert len(pushes) == 2  # claim, then the terminal result
    assert "claim" in pushes[0] and "sent" in pushes[1]


def test_terminal_persist_failure_is_red_even_when_delivered(env, monkeypatch):
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 32))
    calls = {"n": 0}

    def _push(_msg, **kw):
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


_EXPECTED = {
    "session_key": "us_open:2026-07-20",
    "delivery_state": "claimed",
    "workflow_attempt_id": "run-42:1",
}


def _remote_with(expected, delivery_state=None, attempt_id=None):
    """A remote state file (as `git show` would return) containing a record."""
    return json.dumps({
        "schema_version": 1,
        "sessions": {
            expected["session_key"]: {
                "session_key": expected["session_key"],
                "delivery_state": delivery_state or expected["delivery_state"],
                "workflow_attempt_id": attempt_id or expected["workflow_attempt_id"],
            }
        },
    })


def _fake_git(fail=(), staged_empty=False, remote_state=None, calls=None):
    """A fake git runner. `remote_state` is the JSON `git show origin:...` returns."""
    from types import SimpleNamespace

    content = remote_state if remote_state is not None else '{"sessions": {}}'

    def run(*args):
        if calls is not None:
            calls.append(args)
        sub = args[0]
        if sub in fail:
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        if sub == "diff":  # diff --cached --quiet: rc 0 == nothing staged
            return SimpleNamespace(returncode=0 if staged_empty else 1,
                                   stdout="", stderr="")
        if sub == "show":  # origin/<branch>:<state file>
            return SimpleNamespace(returncode=0, stdout=content, stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return run


def test_durable_push_disabled_makes_no_git_calls(monkeypatch):
    monkeypatch.delenv("US_OPEN_DURABLE_STATE", raising=False)
    calls = []
    monkeypatch.setattr(rub, "_git_run", _fake_git(calls=calls))
    assert rub._durable_push("m", expected=_EXPECTED) == rub.PUSH_DISABLED
    assert calls == []


def test_durable_push_ok_only_when_remote_contains_record(monkeypatch):
    # Independent-checkout model: OK only when origin's state has our exact record.
    monkeypatch.setenv("US_OPEN_DURABLE_STATE", "1")
    monkeypatch.setattr(rub, "_sleep", lambda s: None)
    monkeypatch.setattr(rub, "_git_run",
                        _fake_git(remote_state=_remote_with(_EXPECTED)))
    assert rub._durable_push("m", expected=_EXPECTED) == rub.PUSH_OK


def test_durable_push_noop_when_remote_missing_record_is_failed(monkeypatch):
    # push exit 0 but the remote state does not contain the record: NOT durable.
    monkeypatch.setenv("US_OPEN_DURABLE_STATE", "1")
    monkeypatch.setattr(rub, "_sleep", lambda s: None)
    monkeypatch.setattr(rub, "_git_run",
                        _fake_git(remote_state='{"sessions": {}}'))
    assert rub._durable_push("m", expected=_EXPECTED) == rub.PUSH_FAILED


def test_durable_push_wrong_attempt_id_on_remote_is_failed(monkeypatch):
    # remote has the session but a DIFFERENT attempt id (e.g. a re-run): not ours.
    monkeypatch.setenv("US_OPEN_DURABLE_STATE", "1")
    monkeypatch.setattr(rub, "_sleep", lambda s: None)
    monkeypatch.setattr(rub, "_git_run",
                        _fake_git(remote_state=_remote_with(
                            _EXPECTED, attempt_id="run-42:2")))
    assert rub._durable_push("m", expected=_EXPECTED) == rub.PUSH_FAILED


def test_durable_push_blocks_foreign_unresolved_claim_as_conflict(monkeypatch):
    # A re-run (same run id, new attempt, stale checkout) must not steal attempt
    # 1's unresolved claim: block_foreign_claim -> PUSH_CONFLICT_CLAIM, no overwrite.
    monkeypatch.setenv("US_OPEN_DURABLE_STATE", "1")
    monkeypatch.setattr(rub, "_sleep", lambda s: None)
    foreign = _remote_with(_EXPECTED, delivery_state="claimed",
                           attempt_id="run-42:1")
    mine = dict(_EXPECTED, workflow_attempt_id="run-42:2")
    monkeypatch.setattr(rub, "_git_run", _fake_git(remote_state=foreign))
    assert rub._durable_push("m", expected=mine, block_foreign_claim=True) == (
        rub.PUSH_CONFLICT_CLAIM
    )


def test_durable_push_blocks_foreign_sent_as_conflict(monkeypatch):
    # remote already shows the session delivered by another attempt: conflict.
    monkeypatch.setenv("US_OPEN_DURABLE_STATE", "1")
    monkeypatch.setattr(rub, "_sleep", lambda s: None)
    delivered = _remote_with(_EXPECTED, delivery_state="sent",
                             attempt_id="run-9:1")
    monkeypatch.setattr(rub, "_git_run", _fake_git(remote_state=delivered))
    assert rub._durable_push("m", expected=_EXPECTED, block_foreign_claim=True) == (
        rub.PUSH_CONFLICT_SENT
    )


def test_durable_push_cas_malformed_remote_is_failed_not_raise(monkeypatch):
    # A structurally-malformed pre-claim remote (`sessions` is a list) must map to
    # a controlled PUSH_FAILED via the shared validator — never an uncaught throw
    # that would reach the trailing generic state writer, and never a send.
    monkeypatch.setenv("US_OPEN_DURABLE_STATE", "1")
    monkeypatch.setattr(rub, "_sleep", lambda s: None)
    monkeypatch.setattr(rub, "_git_run",
                        _fake_git(remote_state='{"sessions": [{}]}'))
    assert rub._durable_push("m", expected=_EXPECTED,
                             block_foreign_claim=True) == rub.PUSH_FAILED


def test_durable_push_cas_unreadable_present_path_never_proceeds(monkeypatch):
    # `git show` fails generically while the path IS present in the tree: the CAS
    # must NOT proceed to add/commit/pull/push on a stale base, and returns FAILED.
    from types import SimpleNamespace
    monkeypatch.setenv("US_OPEN_DURABLE_STATE", "1")
    monkeypatch.setattr(rub, "_sleep", lambda s: None)
    calls = []

    def fake(*args):
        calls.append(args)
        sub = args[0]
        if sub == "show":
            return SimpleNamespace(returncode=128, stdout="", stderr="bad object")
        if sub == "ls-tree":  # path present but unreadable -> not absence
            return SimpleNamespace(
                returncode=0,
                stdout="100644 blob dead\tdata_store/us_open_delivery_state.json\n",
                stderr="",
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(rub, "_git_run", fake)
    assert rub._durable_push("m", expected=_EXPECTED,
                             block_foreign_claim=True) == rub.PUSH_FAILED
    assert not any(a[0] == "commit" for a in calls)  # never committed on stale base
    assert not any(a[0] == "push" for a in calls)


def test_durable_push_cas_verified_absent_path_allows_first_claim(monkeypatch):
    # Only a PROVABLY absent path (ls-tree empty) bootstraps a genuine first
    # claim: the push proceeds and verifies our record on origin.
    from types import SimpleNamespace
    monkeypatch.setenv("US_OPEN_DURABLE_STATE", "1")
    monkeypatch.setattr(rub, "_sleep", lambda s: None)
    calls = []

    def fake(*args):
        calls.append(args)
        sub = args[0]
        if sub == "show":
            if any(a[0] == "push" for a in calls):  # post-push verify: our record
                return SimpleNamespace(returncode=0,
                                       stdout=_remote_with(_EXPECTED), stderr="")
            return SimpleNamespace(returncode=128, stdout="", stderr="absent")
        if sub == "ls-tree":  # empty output -> path provably absent
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if sub == "diff":  # something staged
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(rub, "_git_run", fake)
    assert rub._durable_push("m", expected=_EXPECTED,
                             block_foreign_claim=True) == rub.PUSH_OK
    assert any(a[0] == "push" for a in calls)  # DID proceed to a real push


def test_durable_push_own_claim_is_not_foreign(monkeypatch):
    # our own attempt's claim already on origin: not foreign, verified -> OK.
    monkeypatch.setenv("US_OPEN_DURABLE_STATE", "1")
    monkeypatch.setattr(rub, "_sleep", lambda s: None)
    monkeypatch.setattr(rub, "_git_run",
                        _fake_git(remote_state=_remote_with(_EXPECTED)))
    assert rub._durable_push("m", expected=_EXPECTED, block_foreign_claim=True) == (
        rub.PUSH_OK
    )


def test_durable_push_recovers_from_nonff_race_via_clean_index_rebase(monkeypatch):
    # attempt 1 commits and pushes but the record isn't on origin yet (race);
    # attempt 2 has a CLEAN index yet must still rebase and recover.
    from types import SimpleNamespace
    monkeypatch.setenv("US_OPEN_DURABLE_STATE", "1")
    monkeypatch.setattr(rub, "_sleep", lambda s: None)
    state = {"iter": 0, "clean_rebases": 0}

    def fake(*args):
        sub = args[0]
        if sub == "add":
            state["iter"] += 1
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if sub == "diff":  # iter 1 staged (rc1); iter 2+ already committed (rc0)
            return SimpleNamespace(returncode=0 if state["iter"] >= 2 else 1,
                                   stdout="", stderr="")
        if sub == "pull":
            if state["iter"] >= 2:  # rebase on a clean-index retry
                state["clean_rebases"] += 1
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if sub == "show":  # verify: record present only from iter 2 onward
            content = _remote_with(_EXPECTED) if state["iter"] >= 2 else '{"sessions": {}}'
            return SimpleNamespace(returncode=0, stdout=content, stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(rub, "_git_run", fake)
    assert rub._durable_push("m", expected=_EXPECTED) == rub.PUSH_OK
    assert state["clean_rebases"] >= 1  # retried the rebase despite a clean index


def test_durable_push_add_failure_is_failed(monkeypatch):
    monkeypatch.setenv("US_OPEN_DURABLE_STATE", "1")
    monkeypatch.setattr(rub, "_sleep", lambda s: None)
    monkeypatch.setattr(rub, "_git_run",
                        _fake_git(fail={"add"}, remote_state=_remote_with(_EXPECTED)))
    assert rub._durable_push("m", expected=_EXPECTED) == rub.PUSH_FAILED


def test_durable_push_commit_failure_is_failed(monkeypatch):
    monkeypatch.setenv("US_OPEN_DURABLE_STATE", "1")
    monkeypatch.setattr(rub, "_sleep", lambda s: None)
    monkeypatch.setattr(rub, "_git_run",
                        _fake_git(fail={"commit"}, remote_state=_remote_with(_EXPECTED)))
    assert rub._durable_push("m", expected=_EXPECTED) == rub.PUSH_FAILED


def test_durable_push_fetch_failure_is_failed(monkeypatch):
    monkeypatch.setenv("US_OPEN_DURABLE_STATE", "1")
    monkeypatch.setattr(rub, "_sleep", lambda s: None)
    monkeypatch.setattr(rub, "_git_run",
                        _fake_git(fail={"fetch"}, remote_state=_remote_with(_EXPECTED)))
    assert rub._durable_push("m", expected=_EXPECTED) == rub.PUSH_FAILED


def test_durable_push_rebase_conflict_aborts_and_fails(monkeypatch):
    monkeypatch.setenv("US_OPEN_DURABLE_STATE", "1")
    monkeypatch.setattr(rub, "_sleep", lambda s: None)
    calls = []
    monkeypatch.setattr(rub, "_git_run",
                        _fake_git(fail={"pull"}, calls=calls,
                                  remote_state=_remote_with(_EXPECTED)))
    assert rub._durable_push("m", expected=_EXPECTED) == rub.PUSH_FAILED
    assert any(a[0] == "rebase" and "--abort" in a for a in calls)


def test_durable_push_clean_tree_with_record_already_remote_is_ok(monkeypatch):
    # Nothing staged (claim already committed), and origin already has our record.
    monkeypatch.setenv("US_OPEN_DURABLE_STATE", "1")
    monkeypatch.setattr(rub, "_sleep", lambda s: None)
    monkeypatch.setattr(rub, "_git_run",
                        _fake_git(staged_empty=True,
                                  remote_state=_remote_with(_EXPECTED)))
    assert rub._durable_push("m", expected=_EXPECTED) == rub.PUSH_OK


# --- phase can change DURING the (slow) durable claim push -------------------

def test_clock_advances_during_push_crosses_to_late(env, monkeypatch):
    clock = {"t": _tpe(2026, 7, 20, 21, 39)}  # +9 on_time
    monkeypatch.setattr(rub, "_now_taipei", lambda: clock["t"])
    captured = []

    def _push(_msg, **kw):
        clock["t"] = _tpe(2026, 7, 20, 21, 41)  # +11 while pushing
        return rub.PUSH_OK

    monkeypatch.setattr(rub, "_durable_push", _push)
    monkeypatch.setattr(rub, "_send_detailed", _sender("sent", sink=captured))

    rc = rub.main()

    assert rc == 0
    assert _read(env)["status"] == "late"  # decided AFTER the push
    assert "延遲補發" in captured[0]


def test_clock_advances_during_push_crosses_to_recovery(env, monkeypatch):
    clock = {"t": _tpe(2026, 7, 20, 21, 59)}  # +29 late
    monkeypatch.setattr(rub, "_now_taipei", lambda: clock["t"])
    captured = []
    body_types = []
    monkeypatch.setattr(rub, "_generate_body",
                        lambda bt: body_types.append(bt) or _LEGACY_BODY)

    def _push(_msg, **kw):
        clock["t"] = _tpe(2026, 7, 20, 22, 1)  # +31 while pushing
        return rub.PUSH_OK

    monkeypatch.setattr(rub, "_durable_push", _push)
    monkeypatch.setattr(rub, "_send_detailed", _sender("sent", sink=captured))

    rc = rub.main()

    assert rc == 0
    assert _read(env)["status"] == "intraday_recovery"
    assert "盤中補發" in captured[0]
    assert body_types == ["us_open", "us_midday"]  # body regenerated post-push


def test_clock_advances_during_push_crosses_close_aborts(env, monkeypatch):
    clock = {"t": _tpe(2026, 7, 21, 3, 58)}  # 15:58 ET, intraday_recovery
    monkeypatch.setattr(rub, "_now_taipei", lambda: clock["t"])
    send = _NeverCalled()

    def _push(_msg, **kw):
        clock["t"] = _tpe(2026, 7, 21, 4, 1)  # 16:01 ET, session closed
        return rub.PUSH_OK

    monkeypatch.setattr(rub, "_durable_push", _push)
    monkeypatch.setattr(rub, "_send_detailed", send)

    rc = rub.main()

    assert rc == 1  # closed during the push -> do not send, red miss
    assert send.called is False
    assert _read(env)["status"] == "expired"


def _race_git(hydration_content, cas_content):
    """A fake git where the first `git show` (top-of-main hydration) returns
    `hydration_content` and every later `git show` (CAS pre-read + conflict
    resync) returns `cas_content` — modelling a foreign attempt that lands between
    our hydration and our claim push.
    """
    from types import SimpleNamespace
    shows = {"n": 0}

    def fake(*args):
        sub = args[0]
        if sub == "show":
            shows["n"] += 1
            content = hydration_content if shows["n"] == 1 else cas_content
            return SimpleNamespace(returncode=0, stdout=content, stderr="")
        if sub == "diff":  # claim is staged
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return fake


def test_rerun_does_not_steal_foreign_claim_or_send(durable_env, monkeypatch):
    # GitHub re-run (run-42:2): origin is empty at hydration, but a foreign
    # unresolved claim from attempt run-42:1 lands before our claim push. The CAS
    # must refuse (red, no send) and PRESERVE the foreign record and its owner —
    # no current-attempt replacement for the trailing commit-state to push.
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")  # our attempt id = run-42:2
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 32))
    foreign = _remote_with(_EXPECTED, delivery_state="claimed",
                           attempt_id="run-42:1")
    monkeypatch.setattr(rub, "_git_run",
                        _race_git('{"sessions": {}}', foreign))
    send = _NeverCalled()
    monkeypatch.setattr(rub, "_send_detailed", send)

    rc = rub.main()

    assert rc == 1
    assert send.called is False
    rec = _read(durable_env)
    # Foreign owner preserved exactly; NOT replaced by our attempt or 'ambiguous'.
    assert rec["delivery_state"] == "claimed"
    assert rec["workflow_attempt_id"] == "run-42:1"


def test_race_remote_sent_after_hydration_is_duplicate_green(durable_env, monkeypatch):
    # A foreign attempt DELIVERS between our hydration and our claim push. The CAS
    # sees remote 'sent' -> clean duplicate (green), no send, remote sent record
    # preserved (no current-attempt replacement).
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 32))
    delivered = _remote_with(_EXPECTED, delivery_state="sent",
                             attempt_id="run-9:1")
    monkeypatch.setattr(rub, "_git_run",
                        _race_git('{"sessions": {}}', delivered))
    send = _NeverCalled()
    monkeypatch.setattr(rub, "_send_detailed", send)

    rc = rub.main()

    assert rc == 0  # duplicate green
    assert send.called is False
    rec = _read(durable_env)
    assert rec["delivery_state"] == "sent"
    assert rec["workflow_attempt_id"] == "run-9:1"  # foreign delivery preserved


def test_stabilization_regen_failure_is_red_and_retryable(env, monkeypatch):
    # Clock crosses +30 during the claim push; the intraday body regeneration
    # raises. The durable claim must NOT be left 'claimed' (false ambiguity):
    # persist a retryable failed/generation_failed and never call Telegram.
    clock = {"t": _tpe(2026, 7, 20, 21, 59)}  # +29 late
    monkeypatch.setattr(rub, "_now_taipei", lambda: clock["t"])
    calls = {"n": 0}

    def _gen(_bt):
        calls["n"] += 1
        if calls["n"] == 1:
            return _LEGACY_BODY  # initial us_open body succeeds
        raise RuntimeError("intraday builder down")  # regeneration fails

    monkeypatch.setattr(rub, "_generate_body", _gen)

    def _push(_msg, **kw):
        clock["t"] = _tpe(2026, 7, 20, 22, 1)  # +31 during the claim push
        return rub.PUSH_OK

    monkeypatch.setattr(rub, "_durable_push", _push)
    send = _NeverCalled()
    monkeypatch.setattr(rub, "_send_detailed", send)

    rc = rub.main()

    assert rc == 1
    assert send.called is False
    rec = _read(env)
    assert rec["delivery_state"] == DELIVERY_FAILED  # not stuck 'claimed'
    assert rec["stage_code"] == "generation_failed"  # retryable in-window


def _seed(store, dt, delivery_state, **kw):
    store.upsert(new_record(
        resolve_us_open_session(dt),
        status=kw.get("status"), lateness_minutes=kw.get("lateness", 0),
        schedule_source="prior", workflow_run_id="run-1",
        workflow_started_at=dt.isoformat(), delivery_state=delivery_state,
    ))


def test_hydration_remote_sent_is_skipped_as_duplicate(env, monkeypatch):
    # A stale-checkout run whose hydrated origin state shows 'sent' skips as a
    # clean duplicate (green) and never calls Telegram.
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 32))

    def _hydrate(store):
        _seed(store, _tpe(2026, 7, 20, 21, 32), DELIVERY_SENT, status="on_time")
        return True

    monkeypatch.setattr(rub, "_hydrate_local_from_remote", _hydrate)
    send = _NeverCalled()
    monkeypatch.setattr(rub, "_send_detailed", send)

    rc = rub.main()

    assert rc == 0
    assert send.called is False
    assert _read(env)["delivery_state"] == DELIVERY_SENT


def test_hydration_remote_claimed_is_not_replaced_or_sent(env, monkeypatch):
    _freeze(monkeypatch, _tpe(2026, 7, 20, 21, 32))

    def _hydrate(store):
        _seed(store, _tpe(2026, 7, 20, 21, 32), DELIVERY_CLAIMED, status="on_time")
        return True

    monkeypatch.setattr(rub, "_hydrate_local_from_remote", _hydrate)
    send = _NeverCalled()
    monkeypatch.setattr(rub, "_send_detailed", send)

    rc = rub.main()

    assert rc == 1  # unresolved remote claim -> surface, do not send
    assert send.called is False
    assert _read(env)["delivery_state"] == DELIVERY_AMBIGUOUS


def test_hydration_malformed_remote_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("US_OPEN_DURABLE_STATE", "1")
    from types import SimpleNamespace

    def fake(*args):
        if args[0] == "show":
            return SimpleNamespace(returncode=0, stdout='{"sessions": []}', stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(rub, "_git_run", fake)
    store = UsOpenDeliveryStore(tmp_path / "s.json")
    with pytest.raises(StateReadError):
        rub._hydrate_local_from_remote(store)


def test_hydrate_local_from_remote_writes_origin_content(tmp_path, monkeypatch):
    monkeypatch.setenv("US_OPEN_DURABLE_STATE", "1")
    from types import SimpleNamespace
    remote = _remote_with(_EXPECTED, delivery_state="sent")

    def fake(*args):
        if args[0] == "show":
            return SimpleNamespace(returncode=0, stdout=remote, stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(rub, "_git_run", fake)
    store = UsOpenDeliveryStore(tmp_path / "s.json")
    assert rub._hydrate_local_from_remote(store) is True
    assert store.get("us_open:2026-07-20")["delivery_state"] == "sent"


def test_hydration_generic_show_failure_with_present_path_fails_closed(
    tmp_path, monkeypatch
):
    # `git show` fails generically but the path IS present in origin's tree: a
    # transient/unreadable object must fail closed, NOT be read as an empty first
    # run, so a stale checkout can never become authoritative.
    monkeypatch.setenv("US_OPEN_DURABLE_STATE", "1")
    from types import SimpleNamespace

    def fake(*args):
        sub = args[0]
        if sub == "show":
            return SimpleNamespace(returncode=128, stdout="", stderr="bad object")
        if sub == "ls-tree":
            return SimpleNamespace(
                returncode=0,
                stdout="100644 blob abc\tdata_store/us_open_delivery_state.json\n",
                stderr="",
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(rub, "_git_run", fake)
    store = UsOpenDeliveryStore(tmp_path / "s.json")
    with pytest.raises(StateReadError):
        rub._hydrate_local_from_remote(store)


def test_hydration_verified_absent_path_bootstraps(tmp_path, monkeypatch):
    # Only a PROVABLY absent path (ls-tree empty output) is a legitimate first
    # run: hydration keeps the local base and returns True without failing closed.
    monkeypatch.setenv("US_OPEN_DURABLE_STATE", "1")
    from types import SimpleNamespace

    def fake(*args):
        sub = args[0]
        if sub == "show":
            return SimpleNamespace(returncode=128, stdout="", stderr="no such path")
        if sub == "ls-tree":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(rub, "_git_run", fake)
    store = UsOpenDeliveryStore(tmp_path / "s.json")
    assert rub._hydrate_local_from_remote(store) is True


def test_same_status_clock_advance_updates_lateness_on_failure(env, monkeypatch):
    # Clock advances during the claim push but stays on_time; a failed send must
    # persist the request-time lateness, not the generation-time value.
    clock = {"t": _tpe(2026, 7, 20, 21, 32)}  # +2 on_time
    monkeypatch.setattr(rub, "_now_taipei", lambda: clock["t"])

    def _push(_msg, **kw):
        clock["t"] = _tpe(2026, 7, 20, 21, 37)  # +7, still on_time
        return rub.PUSH_OK

    monkeypatch.setattr(rub, "_durable_push", _push)
    monkeypatch.setattr(rub, "_send_detailed", _sender("failed", delivered=0))

    rc = rub.main()

    assert rc == 1
    rec = _read(env)
    assert rec["delivery_state"] == DELIVERY_FAILED
    assert rec["lateness_minutes"] == 7  # request-time, not +2 generation-time


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
