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


# --- end-to-end: real main() in durable mode over one shared origin ----------


class _Origin:
    """A shared authoritative origin backed by a fake git for main() runs.

    ``push`` makes the CURRENT checkout's local ledger durable on origin;
    ``show`` returns it. Rewire per run to that run's local path, so two runs on
    *different* local paths still share one authoritative remote — a genuine
    independent-checkout model, not a reopened temp file.
    """

    def __init__(self):
        self.content = None  # None == provably absent (genuine first run)

    def git_for(self, local_path, *, fail_terminal_push=False):
        def run(*args):
            sub = args[0]
            if sub == "diff":
                return _rc(1)  # something staged -> commit proceeds
            if sub == "show":
                if self.content is None:
                    return _rc(128, stderr="bad object")
                return _rc(0, stdout=self.content)
            if sub == "ls-tree":
                return _rc(
                    0, stdout="" if self.content is None else "100644 blob x\tp\n"
                )
            if sub == "push":
                try:
                    local = open(local_path, encoding="utf-8").read()
                except OSError:
                    return _rc(1)
                if fail_terminal_push:
                    posts = json.loads(local).get("posts", {})
                    if any(
                        r.get("delivery_state") in ("sent", "failed", "ambiguous")
                        for r in posts.values()
                    ):
                        return _rc(1)  # terminal push fails; remote unchanged
                self.content = local
                return _rc(0)
            return _rc(0)

        return run


def _wire(monkeypatch, *, local_path, git, posts, outcome="sent",
          run_id="run-A", run_attempt="1", on_send=None, archive_raises=False):
    state = {"sent": [], "writes": {}}
    monkeypatch.setenv("TRUMP_DURABLE_STATE", "1")
    monkeypatch.setenv("GITHUB_RUN_ID", run_id)
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", run_attempt)
    monkeypatch.setattr(tdr, "_git_run", git)
    monkeypatch.setattr(tdr, "_sleep", lambda s: None)
    monkeypatch.setattr(
        run_trump_monitor, "fetch_recent_posts_with_health", lambda: _healthy(posts)
    )
    monkeypatch.setattr(
        run_trump_monitor,
        "TrumpDeliveryStore",
        lambda: TrumpDeliveryStore(path=local_path, legacy_path=None),
    )
    if archive_raises:
        def _raise(_):
            raise trump_truth.ArchiveError("archive corrupt")
        monkeypatch.setattr(run_trump_monitor, "archive_posts", _raise)
    else:
        monkeypatch.setattr(run_trump_monitor, "archive_posts", lambda v: len(v))
    monkeypatch.setattr(run_trump_monitor, "get_default_translator", lambda: None)

    def _send(message, **kwargs):
        if on_send is not None:
            on_send()
        state["sent"].append((message, kwargs))
        return {"outcome": outcome, "delivered": 1, "total": 1}

    monkeypatch.setattr(run_trump_monitor, "send_telegram_detailed", _send)
    monkeypatch.setattr(run_trump_monitor, "send_telegram", lambda *a, **k: True)
    monkeypatch.setattr(run_trump_monitor, "read_json", lambda *a, **k: {})
    monkeypatch.setattr(
        run_trump_monitor,
        "write_json",
        lambda f, v: state["writes"].__setitem__(f, v) or True,
    )
    return state


def _remote_posts(origin):
    return json.loads(origin.content)["posts"] if origin.content else {}


def test_e2e_stale_checkout_after_remote_sent_does_not_resend(monkeypatch):
    # Run A (checkout A) delivers X; origin records X=sent. Run B is a genuinely
    # independent checkout (different local path, empty local ledger) that shares
    # the same origin: it must hydrate origin and NOT resend X.
    origin = _Origin()
    post = _post("X", "tariff news")

    path_a = os.path.join(tempfile.mkdtemp(), "ledger.json")
    st_a = _wire(monkeypatch, local_path=path_a, git=origin.git_for(path_a),
                 posts=[post], run_id="run-A")
    assert run_trump_monitor.main() == 0
    assert [m for m, _ in st_a["sent"]]  # A delivered
    assert _remote_posts(origin)["X"]["delivery_state"] == "sent"

    path_b = os.path.join(tempfile.mkdtemp(), "ledger.json")  # separate checkout
    assert not os.path.exists(path_b)
    st_b = _wire(monkeypatch, local_path=path_b, git=origin.git_for(path_b),
                 posts=[post], run_id="run-B")
    assert run_trump_monitor.main() == 0
    assert st_b["sent"] == []  # hydrated origin; never resent


def test_e2e_stale_checkout_preserves_foreign_claim_and_stays_red(monkeypatch):
    # Origin holds a FOREIGN unresolved claim for X (another attempt, possibly
    # still completing). A stale independent checkout must NOT steal, overwrite,
    # convert, or resend it; it stays red on the unresolved backlog and the
    # foreign record is preserved exactly on origin.
    origin = _Origin()
    origin.content = _ledger_json({
        "X": {
            "post_id": "X", "delivery_state": "claimed",
            "workflow_attempt_id": "run-OTHER:1", "created_at": None,
            "source": None, "claimed_at": "t", "resolved_at": None,
            "run_id": "run-OTHER", "stage_code": "claimed_before_send",
        }
    })
    post = _post("X")
    path = os.path.join(tempfile.mkdtemp(), "ledger.json")
    st = _wire(monkeypatch, local_path=path, git=origin.git_for(path),
               posts=[post], run_id="run-MINE")
    assert run_trump_monitor.main() == 1  # red, no send
    assert st["sent"] == []
    health = st["writes"]["trump_monitor_health.json"]
    assert health["delivery_status"] == "unresolved_delivery_backlog"
    rec = _remote_posts(origin)["X"]
    assert rec["delivery_state"] == "claimed"  # preserved, never converted
    assert rec["workflow_attempt_id"] == "run-OTHER:1"  # preserved exactly


def test_e2e_claim_before_send_is_durable_on_origin(monkeypatch):
    # At the moment Telegram is called, origin must already carry our claim: the
    # claim is remote-verified BEFORE the non-idempotent send.
    origin = _Origin()
    post = _post("X")
    path = os.path.join(tempfile.mkdtemp(), "ledger.json")
    seen_at_send = {}

    def _on_send():
        seen_at_send["state"] = (
            _remote_posts(origin).get("X", {}).get("delivery_state")
        )

    _wire(monkeypatch, local_path=path, git=origin.git_for(path),
          posts=[post], run_id="run-A", on_send=_on_send)
    assert run_trump_monitor.main() == 0
    assert seen_at_send["state"] == "claimed"  # claim durable before send
    assert _remote_posts(origin)["X"]["delivery_state"] == "sent"


def test_e2e_terminal_push_failure_after_send_is_red(monkeypatch):
    # The send happens but its terminal result cannot be verified on origin: the
    # run must be red so the next run does not misread a delivered post.
    origin = _Origin()
    post = _post("X")
    path = os.path.join(tempfile.mkdtemp(), "ledger.json")
    st = _wire(
        monkeypatch, local_path=path,
        git=origin.git_for(path, fail_terminal_push=True), posts=[post],
    )
    assert run_trump_monitor.main() == 1
    assert len(st["sent"]) >= 1  # it DID send
    health = st["writes"]["trump_monitor_health.json"]
    assert health["delivery_status"] == "delivery_blocked_not_durable"


def test_e2e_backlog_only_run_stays_red_and_sends_nothing(monkeypatch):
    # Origin already holds an ambiguous record and there is no new post: the run
    # must stay red (unresolved backlog) and send nothing.
    origin = _Origin()
    origin.content = _ledger_json({
        "old": {"post_id": "old", "delivery_state": "ambiguous",
                "workflow_attempt_id": "run-Z:1", "created_at": None,
                "source": None, "claimed_at": None, "resolved_at": "t",
                "run_id": "run-Z", "stage_code": "resolved_ambiguous"}
    })
    path = os.path.join(tempfile.mkdtemp(), "ledger.json")
    st = _wire(monkeypatch, local_path=path, git=origin.git_for(path), posts=[])
    assert run_trump_monitor.main() == 1
    assert st["sent"] == []
    health = st["writes"]["trump_monitor_health.json"]
    assert health["delivery_status"] == "unresolved_delivery_backlog"


def test_e2e_archive_failure_prevents_any_send(monkeypatch):
    origin = _Origin()
    post = _post("X")
    path = os.path.join(tempfile.mkdtemp(), "ledger.json")
    st = _wire(monkeypatch, local_path=path, git=origin.git_for(path),
               posts=[post], archive_raises=True)
    assert run_trump_monitor.main() == 1
    assert st["sent"] == []  # never sent when the post could not be archived
    health = st["writes"]["trump_monitor_health.json"]
    assert health["delivery_status"] == "archive_unavailable_fail_closed"
    assert _remote_posts(origin) == {}  # nothing claimed/sent on origin


def test_e2e_corrupt_legacy_bootstrap_fails_closed(monkeypatch):
    # Ledger absent on origin (first run) but the committed legacy seen file is
    # corrupt: bootstrapping an empty ledger would re-blast. Fail closed.
    origin = _Origin()  # content None -> provably absent
    legacy_path = os.path.join(tempfile.mkdtemp(), "trump_seen_posts.json")
    with open(legacy_path, "w", encoding="utf-8") as fh:
        fh.write("{ not valid json ")
    ledger_path = os.path.join(tempfile.mkdtemp(), "ledger.json")
    post = _post("X")

    monkeypatch.setenv("TRUMP_DURABLE_STATE", "1")
    monkeypatch.setenv("GITHUB_RUN_ID", "run-A")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setattr(tdr, "_git_run", origin.git_for(ledger_path))
    monkeypatch.setattr(tdr, "_sleep", lambda s: None)
    monkeypatch.setattr(
        run_trump_monitor, "fetch_recent_posts_with_health", lambda: _healthy([post])
    )
    monkeypatch.setattr(
        run_trump_monitor,
        "TrumpDeliveryStore",
        lambda: TrumpDeliveryStore(path=ledger_path, legacy_path=legacy_path),
    )
    monkeypatch.setattr(run_trump_monitor, "archive_posts", lambda v: len(v))
    monkeypatch.setattr(run_trump_monitor, "get_default_translator", lambda: None)
    sent = []
    monkeypatch.setattr(
        run_trump_monitor, "send_telegram_detailed",
        lambda m, **k: sent.append(m) or {"outcome": "sent"},
    )
    monkeypatch.setattr(run_trump_monitor, "send_telegram", lambda *a, **k: True)
    writes = {}
    monkeypatch.setattr(run_trump_monitor, "read_json", lambda *a, **k: {})
    monkeypatch.setattr(
        run_trump_monitor, "write_json",
        lambda f, v: writes.__setitem__(f, v) or True,
    )

    assert run_trump_monitor.main() == 1
    assert sent == []
    assert writes["trump_monitor_health.json"]["delivery_status"] == (
        "state_unreadable_fail_closed"
    )
