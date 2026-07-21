"""Direct unit tests for the durable Trump delivery ledger.

The ledger is the exactly-once backbone of the Trump monitor: it must fail
closed on a corrupt file, never downgrade a durable success, quarantine an
unresolved claim as ambiguous, write atomically, and expose only public-safe
fields (post IDs / states / timestamps — never post text, chat IDs or tokens).
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from src.storage.trump_delivery_state import (
    DELIVERY_AMBIGUOUS,
    DELIVERY_CLAIMED,
    DELIVERY_FAILED,
    DELIVERY_SENT,
    DO_AMBIGUOUS,
    DO_PROCEED,
    DO_RETRY,
    DO_SKIP_AMBIGUOUS,
    DO_SKIP_SENT,
    STATE_SCHEMA_VERSION,
    StateReadError,
    TrumpDeliveryStore,
    resolve_delivery_action,
)


def _store(tmp_path):
    return TrumpDeliveryStore(
        path=os.path.join(tmp_path, "trump_delivery_state.json"),
        legacy_path=None,
    )


def _post(post_id="p1"):
    return {
        "id": post_id,
        "created_at": "2026-07-21T00:00:00+00:00",
        "source": "truth_social_official_api",
    }


# --- action resolution ------------------------------------------------------


def test_resolve_action_for_each_state():
    assert resolve_delivery_action(None) == DO_PROCEED
    assert resolve_delivery_action({}) == DO_PROCEED
    assert resolve_delivery_action({"delivery_state": DELIVERY_SENT}) == DO_SKIP_SENT
    assert (
        resolve_delivery_action({"delivery_state": DELIVERY_AMBIGUOUS})
        == DO_SKIP_AMBIGUOUS
    )
    # A durable 'claimed' can only be a crashed run -> quarantine, do not resend.
    assert resolve_delivery_action({"delivery_state": DELIVERY_CLAIMED}) == DO_AMBIGUOUS
    assert resolve_delivery_action({"delivery_state": DELIVERY_FAILED}) == DO_RETRY


# --- claim / resolve transitions --------------------------------------------


def test_fresh_store_is_empty(tmp_path):
    store = _store(tmp_path)
    assert store.get("p1") is None
    assert store.action_for("p1") == DO_PROCEED
    assert store.capture_started_at() is None


def test_claim_then_resolve_sent_is_terminal(tmp_path):
    store = _store(tmp_path)
    assert store.claim(_post(), run_id="r1")["delivery_state"] == DELIVERY_CLAIMED
    # An unresolved claim, seen by a later run, is ambiguous (crash quarantine).
    assert store.action_for("p1") == DO_AMBIGUOUS

    store.resolve("p1", "sent", run_id="r1")
    assert store.get("p1")["delivery_state"] == DELIVERY_SENT
    assert store.action_for("p1") == DO_SKIP_SENT

    # 'sent' is never downgraded, even on a later failed/ambiguous resolve.
    store.resolve("p1", "failed", run_id="r2")
    assert store.get("p1")["delivery_state"] == DELIVERY_SENT
    store.resolve("p1", "ambiguous", run_id="r2")
    assert store.get("p1")["delivery_state"] == DELIVERY_SENT


def test_claim_on_already_sent_returns_none(tmp_path):
    store = _store(tmp_path)
    store.claim(_post(), run_id="r1")
    store.resolve("p1", "sent", run_id="r1")
    # Never re-claim / downgrade a delivered post (would risk a duplicate blast).
    assert store.claim(_post(), run_id="r2") is None


def test_resolve_failed_and_ambiguous_states(tmp_path):
    store = _store(tmp_path)
    store.claim(_post("f"), run_id="r1")
    store.resolve("f", "failed", run_id="r1")
    assert store.get("f")["delivery_state"] == DELIVERY_FAILED
    assert store.action_for("f") == DO_RETRY

    store.claim(_post("a"), run_id="r1")
    store.resolve("a", "ambiguous", run_id="r1")
    assert store.get("a")["delivery_state"] == DELIVERY_AMBIGUOUS
    assert store.action_for("a") == DO_SKIP_AMBIGUOUS


def test_unknown_outcome_defaults_to_ambiguous(tmp_path):
    # An unrecognized outcome must fail safe (quarantine), never claim success.
    store = _store(tmp_path)
    store.claim(_post(), run_id="r1")
    store.resolve("p1", "weird-outcome", run_id="r1")
    assert store.get("p1")["delivery_state"] == DELIVERY_AMBIGUOUS


# --- fail-closed reads ------------------------------------------------------


def test_missing_file_is_empty_not_error(tmp_path):
    store = _store(tmp_path)
    # No file yet: a legitimate first run, not a corruption.
    assert store.health_counts()[DELIVERY_SENT] == 0


def test_corrupt_file_fails_closed(tmp_path):
    store = _store(tmp_path)
    with open(store.path, "w", encoding="utf-8") as fh:
        fh.write("{ not valid json ")
    with pytest.raises(StateReadError):
        store.get("p1")


def test_non_object_payload_fails_closed(tmp_path):
    store = _store(tmp_path)
    with open(store.path, "w", encoding="utf-8") as fh:
        json.dump([1, 2, 3], fh)
    with pytest.raises(StateReadError):
        store.get("p1")


def test_unsupported_delivery_state_fails_closed(tmp_path):
    store = _store(tmp_path)
    with open(store.path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "schema_version": STATE_SCHEMA_VERSION,
                "posts": {"p1": {"delivery_state": "bogus"}},
            },
            fh,
        )
    with pytest.raises(StateReadError):
        store.get("p1")


def test_future_schema_version_fails_closed(tmp_path):
    store = _store(tmp_path)
    with open(store.path, "w", encoding="utf-8") as fh:
        json.dump(
            {"schema_version": STATE_SCHEMA_VERSION + 1, "posts": {}}, fh
        )
    with pytest.raises(StateReadError):
        store.get("p1")


# --- atomic write -----------------------------------------------------------


def test_write_is_atomic_and_leaves_no_temp_files(tmp_path):
    store = _store(tmp_path)
    store.claim(_post(), run_id="r1")
    store.resolve("p1", "sent", run_id="r1")
    # The final file is valid JSON and no .tmp scratch file is left behind.
    on_disk = json.loads(open(store.path, encoding="utf-8").read())
    assert on_disk["posts"]["p1"]["delivery_state"] == DELIVERY_SENT
    leftovers = [n for n in os.listdir(tmp_path) if n.endswith(".tmp")]
    assert leftovers == []


# --- capture checkpoint -----------------------------------------------------


def test_capture_checkpoint_roundtrip_and_idempotent_write(tmp_path):
    store = _store(tmp_path)
    store.set_capture_started_at("2026-07-01T00:00:00+00:00")
    assert store.capture_started_at() == "2026-07-01T00:00:00+00:00"
    mtime = os.path.getmtime(store.path)
    # Setting the identical value must not rewrite the file (no churn/commit).
    store.set_capture_started_at("2026-07-01T00:00:00+00:00")
    assert os.path.getmtime(store.path) == mtime


# --- legacy migration -------------------------------------------------------


def test_legacy_seen_migrates_to_sent_idempotently(tmp_path):
    legacy_path = os.path.join(tmp_path, "trump_seen_posts.json")
    with open(legacy_path, "w", encoding="utf-8") as fh:
        json.dump(
            {"old1": {"created_at": "2026-06-01T00:00:00+00:00", "seen_at": "x"}},
            fh,
        )
    store = TrumpDeliveryStore(
        path=os.path.join(tmp_path, "trump_delivery_state.json"),
        legacy_path=legacy_path,
    )
    assert store.migrate_legacy_seen() == 1
    assert store.get("old1")["delivery_state"] == DELIVERY_SENT
    # Idempotent: a migrated post is never re-migrated or downgraded.
    assert store.migrate_legacy_seen() == 0
    assert store.get("old1")["delivery_state"] == DELIVERY_SENT


def test_no_post_text_or_secrets_in_persisted_record(tmp_path):
    # The ledger is committed to a public repo: it must carry only IDs / states
    # / timestamps, never post text or chat identifiers.
    store = _store(tmp_path)
    store.claim(_post(), run_id="run-123")
    store.resolve("p1", "sent", run_id="run-123")
    raw = open(store.path, encoding="utf-8").read()
    record = json.loads(raw)["posts"]["p1"]
    assert set(record).issubset(
        {
            "post_id",
            "created_at",
            "source",
            "delivery_state",
            "claimed_at",
            "resolved_at",
            "run_id",
            "stage_code",
        }
    )
    assert "text" not in raw
