"""Durable, authoritative-remote delivery regressions for the Trump monitor.

These exercise the reliability round from review 4744799949: the delivery
decision must be made against ``origin/main``'s authoritative ledger (not a
possibly-stale event checkout), each per-post claim/terminal transition must be
compare-and-set verified on origin before/after the non-idempotent Telegram
send, an unresolved backlog must stay operationally red, and archive/legacy
bootstrap failures must fail closed before any send.

Two layers:

- Unit tests drive the real ``durable_push`` / ``hydrate_from_remote`` against a
  fake ``_git_run`` whose "remote" is a shared holder — the independent-checkout
  model (OK only when origin's content actually carries our record).
- End-to-end tests drive the real ``main()`` in durable mode with that fake git,
  using *separate local ledger paths* for each run over one shared origin, so a
  genuinely stale/independent checkout — not a reopened temp path — is modelled.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.data import trump_truth
from src.runners import run_trump_monitor
from src.storage import trump_delivery_remote as tdr
from src.storage.trump_delivery_remote import (
    PUSH_CONFLICT_CLAIM,
    PUSH_CONFLICT_SENT,
    PUSH_DISABLED,
    PUSH_FAILED,
    PUSH_OK,
    durable_push,
    hydrate_from_remote,
)
from src.storage.trump_delivery_state import StateReadError, TrumpDeliveryStore

_STATE_REL = "data_store/trump_delivery_state.json"


def _rc(code=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)


def _post(post_id, text="Policy statement", *, hours_ago=1, tier="tier3"):
    return {
        "id": post_id,
        "created_at": (
            datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        ).isoformat(),
        "url": f"https://truthsocial.com/@realDonaldTrump/{post_id}",
        "text": text,
        "activity_type": "post",
        "source": "truth_social_official_api",
        "original_account": "realDonaldTrump",
        "media_count": 0,
        "tier": tier,
        "matched_keywords": {"tier1": {}, "tier2": {}},
    }


def _healthy(posts):
    return {
        "status": "healthy",
        "source": "truth_social_official_api",
        "latest_post_at": posts[-1]["created_at"] if posts else None,
        "posts": posts,
        "attempts": [],
        "raw_count": len(posts),
        "returned_count": len(posts),
        "source_limit": 1000,
    }


def _ledger_json(records):
    """Build an authoritative-remote ledger JSON string from post records."""
    return json.dumps(
        {"schema_version": 1, "capture_started_at": None, "posts": records}
    )


_EXPECTED = {
    "post_id": "p1",
    "delivery_state": "claimed",
    "workflow_attempt_id": "run-42:1",
}


def _remote_with(expected, *, delivery_state=None, attempt_id=None):
    record = {
        "post_id": expected["post_id"],
        "delivery_state": delivery_state or expected["delivery_state"],
        "workflow_attempt_id": attempt_id or expected["workflow_attempt_id"],
    }
    return _ledger_json({expected["post_id"]: record})


# --- unit: durable_push / hydrate against a fake git remote ------------------


def _fake_git(*, remote=None, staged_empty=False, fail=(), calls=None):
    content = remote

    def run(*args):
        if calls is not None:
            calls.append(args)
        sub = args[0]
        if sub in fail:
            return _rc(1)
        if sub == "diff":
            return _rc(0 if staged_empty else 1)
        if sub == "show":
            if content is None:
                return _rc(128, stderr="bad object")
            return _rc(0, stdout=content)
        if sub == "ls-tree":
            # absent iff we modelled no content and did not force unreadable
            return _rc(0, stdout="" if content is None else "100644 blob x\tp\n")
        return _rc(0)

    return run


def test_durable_push_disabled_makes_no_git_calls(monkeypatch):
    monkeypatch.delenv("TRUMP_DURABLE_STATE", raising=False)
    calls = []
    monkeypatch.setattr(tdr, "_git_run", _fake_git(calls=calls))
    store = TrumpDeliveryStore(path="/nonexistent", legacy_path=None)
    assert durable_push(store, "m", expected=_EXPECTED) == PUSH_DISABLED
    assert calls == []


def test_durable_push_ok_only_when_remote_has_our_record(monkeypatch):
    monkeypatch.setenv("TRUMP_DURABLE_STATE", "1")
    monkeypatch.setattr(tdr, "_sleep", lambda s: None)
    monkeypatch.setattr(tdr, "_git_run", _fake_git(remote=_remote_with(_EXPECTED)))
    store = TrumpDeliveryStore(path="/nonexistent", legacy_path=None)
    assert durable_push(store, "m", expected=_EXPECTED) == PUSH_OK


def test_durable_push_missing_record_is_failed(monkeypatch):
    monkeypatch.setenv("TRUMP_DURABLE_STATE", "1")
    monkeypatch.setattr(tdr, "_sleep", lambda s: None)
    monkeypatch.setattr(tdr, "_git_run", _fake_git(remote=_ledger_json({})))
    store = TrumpDeliveryStore(path="/nonexistent", legacy_path=None)
    assert durable_push(store, "m", expected=_EXPECTED) == PUSH_FAILED


def test_durable_push_wrong_attempt_id_is_failed(monkeypatch):
    # A re-run (same run id, new attempt) must not verify a prior attempt's record.
    monkeypatch.setenv("TRUMP_DURABLE_STATE", "1")
    monkeypatch.setattr(tdr, "_sleep", lambda s: None)
    monkeypatch.setattr(
        tdr, "_git_run",
        _fake_git(remote=_remote_with(_EXPECTED, attempt_id="run-42:2")),
    )
    store = TrumpDeliveryStore(path="/nonexistent", legacy_path=None)
    assert durable_push(store, "m", expected=_EXPECTED) == PUSH_FAILED


def test_durable_push_blocks_foreign_claim_and_sent(monkeypatch):
    monkeypatch.setenv("TRUMP_DURABLE_STATE", "1")
    monkeypatch.setattr(tdr, "_sleep", lambda s: None)
    store = TrumpDeliveryStore(path="/nonexistent", legacy_path=None)

    foreign_claim = _remote_with(
        _EXPECTED, delivery_state="claimed", attempt_id="run-42:1"
    )
    mine = dict(_EXPECTED, workflow_attempt_id="run-42:2")
    monkeypatch.setattr(tdr, "_git_run", _fake_git(remote=foreign_claim))
    assert durable_push(
        store, "m", expected=mine, block_foreign_claim=True
    ) == PUSH_CONFLICT_CLAIM

    delivered = _remote_with(_EXPECTED, delivery_state="sent", attempt_id="run-9:1")
    monkeypatch.setattr(tdr, "_git_run", _fake_git(remote=delivered))
    assert durable_push(
        store, "m", expected=_EXPECTED, block_foreign_claim=True
    ) == PUSH_CONFLICT_SENT


def test_durable_push_malformed_remote_is_failed_not_raise(monkeypatch):
    monkeypatch.setenv("TRUMP_DURABLE_STATE", "1")
    monkeypatch.setattr(tdr, "_sleep", lambda s: None)
    monkeypatch.setattr(
        tdr, "_git_run", _fake_git(remote='{"posts": [1, 2, 3]}')
    )
    store = TrumpDeliveryStore(path="/nonexistent", legacy_path=None)
    assert durable_push(
        store, "m", expected=_EXPECTED, block_foreign_claim=True
    ) == PUSH_FAILED


def test_durable_push_unreadable_present_path_never_commits(monkeypatch):
    monkeypatch.setenv("TRUMP_DURABLE_STATE", "1")
    monkeypatch.setattr(tdr, "_sleep", lambda s: None)
    calls = []

    def fake(*args):
        calls.append(args)
        sub = args[0]
        if sub == "show":
            return _rc(128, stderr="bad object")
        if sub == "ls-tree":  # present but unreadable -> NOT provably absent
            return _rc(0, stdout=f"100644 blob dead\t{_STATE_REL}\n")
        return _rc(0)

    monkeypatch.setattr(tdr, "_git_run", fake)
    store = TrumpDeliveryStore(path="/nonexistent", legacy_path=None)
    assert durable_push(
        store, "m", expected=_EXPECTED, block_foreign_claim=True
    ) == PUSH_FAILED
    assert not any(a[0] == "commit" for a in calls)
    assert not any(a[0] == "push" for a in calls)


def test_hydrate_disabled_is_noop(monkeypatch, tmp_path):
    monkeypatch.delenv("TRUMP_DURABLE_STATE", raising=False)
    store = TrumpDeliveryStore(path=tmp_path / "l.json", legacy_path=None)
    assert hydrate_from_remote(store) is False


def test_hydrate_overwrites_local_with_remote(monkeypatch, tmp_path):
    monkeypatch.setenv("TRUMP_DURABLE_STATE", "1")
    remote = _ledger_json(
        {"r1": {"post_id": "r1", "delivery_state": "sent"}}
    )
    monkeypatch.setattr(tdr, "_git_run", _fake_git(remote=remote))
    store = TrumpDeliveryStore(path=tmp_path / "l.json", legacy_path=None)
    assert hydrate_from_remote(store) is True
    assert store.get("r1")["delivery_state"] == "sent"


def test_hydrate_fetch_failure_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("TRUMP_DURABLE_STATE", "1")
    monkeypatch.setattr(tdr, "_git_run", _fake_git(fail=("fetch",)))
    store = TrumpDeliveryStore(path=tmp_path / "l.json", legacy_path=None)
    with pytest.raises(StateReadError):
        hydrate_from_remote(store)


def test_hydrate_unreadable_present_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("TRUMP_DURABLE_STATE", "1")

    def fake(*args):
        if args[0] == "show":
            return _rc(128, stderr="bad object")
        if args[0] == "ls-tree":  # present but unreadable
            return _rc(0, stdout=f"100644 blob dead\t{_STATE_REL}\n")
        return _rc(0)

    monkeypatch.setattr(tdr, "_git_run", fake)
    store = TrumpDeliveryStore(path=tmp_path / "l.json", legacy_path=None)
    with pytest.raises(StateReadError):
        hydrate_from_remote(store)


def test_hydrate_verified_absent_bootstraps(monkeypatch, tmp_path):
    monkeypatch.setenv("TRUMP_DURABLE_STATE", "1")
    monkeypatch.setattr(tdr, "_git_run", _fake_git(remote=None))
    store = TrumpDeliveryStore(path=tmp_path / "l.json", legacy_path=None)
    assert hydrate_from_remote(store) is True  # provably absent -> first run


def test_hydrate_malformed_remote_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("TRUMP_DURABLE_STATE", "1")
    monkeypatch.setattr(tdr, "_git_run", _fake_git(remote='{"posts": 5}'))
    store = TrumpDeliveryStore(path=tmp_path / "l.json", legacy_path=None)
    with pytest.raises(StateReadError):
        hydrate_from_remote(store)


# --- archive-specific durable unit tests (fake git) --------------------------

_ARCHIVE_REL = "data_store/trump_posts_archive.json"


def _archive_git(*, ledger=None, archive=None, fail=()):
    """Fake git serving DISTINCT ledger and archive content per path."""

    def run(*args):
        sub = args[0]
        if sub in fail:
            return _rc(1)
        if sub == "diff":
            return _rc(1)  # something staged -> commit proceeds
        if sub == "show":
            ref = args[1]
            if ref.endswith(_ARCHIVE_REL):
                return _rc(0, stdout=archive) if archive is not None else _rc(128)
            return _rc(0, stdout=ledger) if ledger is not None else _rc(128)
        if sub == "ls-tree":
            content = archive if args[-1] == _ARCHIVE_REL else ledger
            return _rc(0, stdout="" if content is None else "100644 blob x\tp\n")
        return _rc(0)

    return run


def test_durable_push_capture_ok_only_when_archive_has_all_ids(monkeypatch):
    monkeypatch.setenv("TRUMP_DURABLE_STATE", "1")
    monkeypatch.setattr(tdr, "_sleep", lambda s: None)
    monkeypatch.setattr(
        tdr, "_git_run",
        _archive_git(ledger='{"posts":{}}', archive='{"a":1,"b":2}'),
    )
    assert tdr.durable_push_capture(["a", "b"], "m") == PUSH_OK


def test_durable_push_capture_failed_when_id_missing(monkeypatch):
    monkeypatch.setenv("TRUMP_DURABLE_STATE", "1")
    monkeypatch.setattr(tdr, "_sleep", lambda s: None)
    monkeypatch.setattr(
        tdr, "_git_run", _archive_git(ledger='{"posts":{}}', archive='{"a":1}')
    )
    assert tdr.durable_push_capture(["a", "b"], "m") == PUSH_FAILED


def test_durable_push_capture_disabled(monkeypatch):
    monkeypatch.delenv("TRUMP_DURABLE_STATE", raising=False)
    assert tdr.durable_push_capture(["a"], "m") == PUSH_DISABLED


def test_hydrate_archive_writes_local(monkeypatch, tmp_path):
    from src.data import trump_truth
    from src.storage import state_manager

    monkeypatch.setenv("TRUMP_DURABLE_STATE", "1")
    monkeypatch.setattr(state_manager, "DATA_STORE_DIR", tmp_path)
    monkeypatch.setattr(tdr, "_git_run", _archive_git(archive='{"a":{"id":"a"}}'))
    assert tdr.hydrate_archive_from_remote() is True
    written = json.loads((tmp_path / trump_truth.ARCHIVE_FILE).read_text())
    assert "a" in written


def test_hydrate_archive_malformed_fails_closed(monkeypatch, tmp_path):
    from src.storage import state_manager

    monkeypatch.setenv("TRUMP_DURABLE_STATE", "1")
    monkeypatch.setattr(state_manager, "DATA_STORE_DIR", tmp_path)
    monkeypatch.setattr(tdr, "_git_run", _archive_git(archive="[1,2,3]"))
    with pytest.raises(StateReadError):
        tdr.hydrate_archive_from_remote()


def test_hydrate_archive_absent_bootstraps(monkeypatch):
    monkeypatch.setenv("TRUMP_DURABLE_STATE", "1")
    monkeypatch.setattr(tdr, "_git_run", _archive_git(archive=None))
    assert tdr.hydrate_archive_from_remote() is True  # provably absent


# --- end-to-end: REAL bare-repo git integration (durable mode) ---------------
# The prior fake-git E2E missed the dirty-worktree rebase break because it never
# created the archive file. These use a real bare origin + working clone(s) so a
# genuinely new archive row must not block the claim rebase, and origin content
# is asserted directly.

_EMPTY_LEDGER = {"schema_version": 1, "capture_started_at": None, "posts": {}}


def _git_cmd(cwd, *args):
    import subprocess

    r = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True
    )
    assert r.returncode == 0, f"git {args} failed: {r.stderr}"
    return r


def _clone(origin, dest):
    _git_cmd(dest.parent, "clone", str(origin), str(dest))
    _git_cmd(dest, "config", "user.email", "t@t.co")
    _git_cmd(dest, "config", "user.name", "t")
    return dest


def _setup_origin(tmp_path, *, ledger, archive):
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    _git_cmd(tmp_path, "init", "--bare", "-b", "main", str(origin))
    _clone(origin, work)
    _git_cmd(work, "symbolic-ref", "HEAD", "refs/heads/main")
    ds = work / "data_store"
    ds.mkdir(parents=True, exist_ok=True)
    (ds / "trump_delivery_state.json").write_text(json.dumps(ledger))
    (ds / "trump_posts_archive.json").write_text(json.dumps(archive))
    _git_cmd(work, "add", "-A")
    _git_cmd(work, "commit", "-m", "seed")
    _git_cmd(work, "push", "-u", "origin", "main")
    return origin, work


def _origin_file(origin, rel):
    import subprocess

    r = subprocess.run(
        ["git", "show", f"main:{rel}"], cwd=str(origin),
        capture_output=True, text=True,
    )
    return json.loads(r.stdout) if r.returncode == 0 else None


def _failed_record(post_id, created_at):
    return {
        "post_id": post_id,
        "created_at": created_at,
        "source": "truth_social_official_api",
        "delivery_state": "failed",
        "claimed_at": None,
        "resolved_at": created_at,
        "run_id": "old",
        "workflow_attempt_id": "old:1",
        "stage_code": "resolved_failed",
    }


def _wire_real(monkeypatch, work, *, posts, outcome="sent", run_id="run-A",
               run_attempt="1", on_send=None):
    from pathlib import Path

    from src.data import trump_truth
    from src.storage import state_manager

    ds = Path(work) / "data_store"
    monkeypatch.chdir(work)
    monkeypatch.setenv("TRUMP_DURABLE_STATE", "1")
    monkeypatch.setenv("GITHUB_RUN_ID", run_id)
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", run_attempt)
    monkeypatch.setattr(tdr, "_sleep", lambda s: None)  # _git_run stays REAL
    monkeypatch.setattr(trump_truth, "DATA_STORE_DIR", ds)
    monkeypatch.setattr(state_manager, "DATA_STORE_DIR", ds)
    monkeypatch.setattr(
        run_trump_monitor, "TrumpDeliveryStore",
        lambda: TrumpDeliveryStore(
            path=str(ds / "trump_delivery_state.json"), legacy_path=None
        ),
    )
    monkeypatch.setattr(
        run_trump_monitor, "fetch_recent_posts_with_health",
        lambda: _healthy(posts),
    )
    monkeypatch.setattr(run_trump_monitor, "get_default_translator", lambda: None)
    sent = []

    def _send(message, **kwargs):
        if on_send is not None:
            on_send()
        sent.append(message)
        return {"outcome": outcome, "delivered": 1, "total": 1}

    monkeypatch.setattr(run_trump_monitor, "send_telegram_detailed", _send)
    monkeypatch.setattr(run_trump_monitor, "send_telegram", lambda *a, **k: True)
    return sent


def test_real_new_post_durable_delivery_and_archive_before_send(
    monkeypatch, tmp_path
):
    # A genuinely new archive row must NOT block the claim rebase (if it did, the
    # claim would be non-durable -> red/no-send), and origin must already hold
    # the archived post at the moment Telegram is called.
    origin, work = _setup_origin(tmp_path, ledger=_EMPTY_LEDGER, archive={})
    seen = {}

    def _on_send():
        seen["archived"] = "X" in (_origin_file(origin, _ARCHIVE_REL) or {})

    sent = _wire_real(monkeypatch, work, posts=[_post("X")], on_send=_on_send)

    assert run_trump_monitor.main() == 0
    assert sent  # delivered: the dirty archive did NOT block claim persistence
    assert seen["archived"] is True  # archive durable on origin BEFORE the send
    assert _origin_file(origin, _STATE_REL)["posts"]["X"]["delivery_state"] == "sent"
    assert "X" in _origin_file(origin, _ARCHIVE_REL)


def test_real_crash_before_trailing_commit_keeps_archive_and_no_resend(
    monkeypatch, tmp_path
):
    # main() pushes ledger+archive durably during the run; a crash BEFORE the
    # trailing commit-state therefore loses neither. A fresh independent checkout
    # must find origin 'sent' + archived and never resend.
    origin, work = _setup_origin(tmp_path, ledger=_EMPTY_LEDGER, archive={})
    sent1 = _wire_real(monkeypatch, work, posts=[_post("X")])
    assert run_trump_monitor.main() == 0
    assert sent1
    assert _origin_file(origin, _STATE_REL)["posts"]["X"]["delivery_state"] == "sent"
    assert "X" in _origin_file(origin, _ARCHIVE_REL)

    work2 = _clone(origin, tmp_path / "work2")
    sent2 = _wire_real(monkeypatch, work2, posts=[_post("X")], run_id="run-B")
    assert run_trump_monitor.main() == 0
    assert sent2 == []  # already sent on origin — no resend
    assert "X" in _origin_file(origin, _ARCHIVE_REL)  # archive preserved


def test_real_failed_absent_from_source_retried_from_archive(monkeypatch, tmp_path):
    # A definitively-failed post that aged OUT of the live source is rebuilt from
    # the authoritative archive, retried, and transitions to remote 'sent'.
    created = "2020-01-02T00:00:00+00:00"
    ledger = {
        "schema_version": 1,
        "capture_started_at": "2020-01-01T00:00:00+00:00",
        "posts": {"X": _failed_record("X", created)},
    }
    origin, work = _setup_origin(
        tmp_path, ledger=ledger, archive={"X": _post("X")}
    )
    sent = _wire_real(monkeypatch, work, posts=[])  # X NOT in the live source
    assert run_trump_monitor.main() == 0
    assert sent  # retried from archive and delivered
    assert _origin_file(origin, _STATE_REL)["posts"]["X"]["delivery_state"] == "sent"


def test_real_failed_missing_archive_is_red_no_send(monkeypatch, tmp_path):
    # A failed record whose archived payload is missing must fail closed: red, no
    # send, and the failure preserved (never a silent green miss).
    ledger = {
        "schema_version": 1,
        "capture_started_at": "2020-01-01T00:00:00+00:00",
        "posts": {"X": _failed_record("X", "2020-01-02T00:00:00+00:00")},
    }
    origin, work = _setup_origin(tmp_path, ledger=ledger, archive={})  # X absent
    sent = _wire_real(monkeypatch, work, posts=[])
    assert run_trump_monitor.main() == 1
    assert sent == []
    assert _origin_file(origin, _STATE_REL)["posts"]["X"]["delivery_state"] == "failed"


def test_real_stale_checkout_after_sent_does_not_resend(monkeypatch, tmp_path):
    # origin already holds X sent + archived; an independent checkout that still
    # sees X in the live source must hydrate origin and never resend.
    ledger = {
        "schema_version": 1,
        "capture_started_at": None,
        "posts": {
            "X": {
                "post_id": "X", "delivery_state": "sent",
                "workflow_attempt_id": "old:1", "created_at": None,
                "source": None, "claimed_at": None,
                "resolved_at": "t", "run_id": "old",
                "stage_code": "resolved_sent",
            }
        },
    }
    origin, work = _setup_origin(
        tmp_path, ledger=ledger, archive={"X": _post("X")}
    )
    sent = _wire_real(monkeypatch, work, posts=[_post("X")])
    assert run_trump_monitor.main() == 0
    assert sent == []  # hydrated origin sent record; no resend
