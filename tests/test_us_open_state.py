"""Delivery state-machine tests for us_open (Issue #13, contract section 4).

Covers claim/sent/failed/ambiguous/skipped semantics, at-most-once under
reorder and pending concurrency, downgrade protection, concurrent-writer
merge (state-write conflict), legacy migration, pruning and corruption.
"""

import json
from datetime import datetime

import pytz

from src.runners.us_open_sla import (
    STATUS_ON_TIME,
    resolve_us_open_session,
)
from src.runners.us_open_state import (
    DELIVERY_AMBIGUOUS,
    DELIVERY_CLAIMED,
    DELIVERY_FAILED,
    DELIVERY_SENT,
    DELIVERY_SKIPPED,
    DO_AMBIGUOUS,
    DO_PROCEED,
    DO_RETRY,
    DO_SKIP_AMBIGUOUS,
    DO_SKIP_DUPLICATE,
    UsOpenDeliveryStore,
    new_record,
    resolve_delivery_action,
)

TAIPEI = pytz.timezone("Asia/Taipei")


def _tpe(y, mo, d, h, mi=0):
    return TAIPEI.localize(datetime(y, mo, d, h, mi))


def _session(y, mo, d, h, mi=0):
    return resolve_us_open_session(_tpe(y, mo, d, h, mi))


def _store(tmp_path, legacy=None):
    return UsOpenDeliveryStore(tmp_path / "us_open_delivery_state.json", legacy)


def _record(session, delivery_state=DELIVERY_CLAIMED, status=STATUS_ON_TIME,
            lateness=0):
    rec = new_record(
        session,
        status=status,
        lateness_minutes=lateness,
        schedule_source="cron 32 13 * * 1-5",
        workflow_run_id="run-1",
        workflow_started_at="2026-07-20T21:32:00+08:00",
        delivery_state=delivery_state,
    )
    return rec


# --- resolve_delivery_action ------------------------------------------------

def test_resolve_none_proceeds():
    assert resolve_delivery_action(None) == DO_PROCEED
    assert resolve_delivery_action({}) == DO_PROCEED


def test_resolve_sent_skips_duplicate():
    assert resolve_delivery_action({"delivery_state": DELIVERY_SENT}) == (
        DO_SKIP_DUPLICATE
    )


def test_resolve_failed_retries():
    assert resolve_delivery_action({"delivery_state": DELIVERY_FAILED}) == DO_RETRY


def test_resolve_claimed_is_ambiguous():
    assert resolve_delivery_action({"delivery_state": DELIVERY_CLAIMED}) == (
        DO_AMBIGUOUS
    )


def test_resolve_ambiguous_stays_skipped():
    assert resolve_delivery_action({"delivery_state": DELIVERY_AMBIGUOUS}) == (
        DO_SKIP_AMBIGUOUS
    )


def test_resolve_skipped_proceeds():
    assert resolve_delivery_action({"delivery_state": DELIVERY_SKIPPED}) == (
        DO_PROCEED
    )


# --- new_record schema ------------------------------------------------------

def test_new_record_has_full_contract_schema():
    rec = _record(_session(2026, 7, 20, 21, 32))
    for field in (
        "schema_version", "brief_type", "session_date_et", "session_key",
        "expected_at_taipei", "workflow_started_at", "generation_started_at",
        "generation_finished_at", "sent_at", "lateness_minutes",
        "schedule_source", "workflow_run_id", "delivery_state", "status",
        "stage_code",
    ):
        assert field in rec
    assert rec["brief_type"] == "us_open"
    assert rec["session_key"] == "us_open:2026-07-20"
    assert rec["expected_at_taipei"].startswith("2026-07-20T21:30")


# --- upsert / get -----------------------------------------------------------

def test_upsert_then_get_roundtrip(tmp_path):
    store = _store(tmp_path)
    rec = _record(_session(2026, 7, 20, 21, 32))
    store.upsert(rec)
    got = store.get("us_open:2026-07-20")
    assert got["delivery_state"] == DELIVERY_CLAIMED


def test_upsert_preserves_other_sessions_written_concurrently(tmp_path):
    """A second writer's session must survive our read-merge-write."""
    store = _store(tmp_path)
    store.upsert(_record(_session(2026, 7, 20, 21, 32)))
    # Simulate another workflow run writing a different session concurrently.
    other = UsOpenDeliveryStore(tmp_path / "us_open_delivery_state.json")
    other.upsert(_record(_session(2026, 7, 21, 21, 32)))
    # Our next write must not clobber the concurrently-added session.
    store.upsert(_record(_session(2026, 7, 20, 21, 40), status=STATUS_ON_TIME))
    assert store.get("us_open:2026-07-20") is not None
    assert store.get("us_open:2026-07-21") is not None


def test_sent_is_never_downgraded_by_later_claim(tmp_path):
    """Telegram success that raced a state write is not lost (contract §4)."""
    store = _store(tmp_path)
    sent = _record(_session(2026, 7, 20, 21, 32), delivery_state=DELIVERY_SENT)
    store.upsert(sent)
    # A late/duplicate attempt tries to write a lower 'claimed' state.
    store.upsert(_record(_session(2026, 7, 20, 21, 40),
                         delivery_state=DELIVERY_CLAIMED))
    assert store.get("us_open:2026-07-20")["delivery_state"] == DELIVERY_SENT


# --- at-most-once under reorder / pending -----------------------------------

def test_reordered_runs_deliver_at_most_once(tmp_path):
    """A later attempt that runs first sends; the earlier one then dedups."""
    store = _store(tmp_path)
    # backup (+9) reaches the runner first and delivers.
    store.upsert(_record(_session(2026, 7, 20, 21, 39), delivery_state=DELIVERY_SENT,
                         lateness=9))
    # primary (+2) runs afterwards -> sees sent -> skip duplicate.
    existing = store.get("us_open:2026-07-20")
    assert resolve_delivery_action(existing) == DO_SKIP_DUPLICATE


def test_pending_second_attempt_sees_claim_and_does_not_duplicate(tmp_path):
    """A crashed prior claim surfaces as ambiguous, never an auto-duplicate."""
    store = _store(tmp_path)
    store.upsert(_record(_session(2026, 7, 20, 21, 32),
                         delivery_state=DELIVERY_CLAIMED))
    existing = store.get("us_open:2026-07-20")
    assert resolve_delivery_action(existing) == DO_AMBIGUOUS


# --- legacy migration -------------------------------------------------------

def test_migrate_legacy_seeds_us_open_only(tmp_path):
    legacy = tmp_path / "brief_sent_today.json"
    legacy.write_text(json.dumps({
        "2026-07-14": {"us_open": True, "us_eod": True, "tw_open": True},
        "2026-07-15": {"us_eod": True},           # no us_open -> skip
        "2026-07-16": {"us_open": False},          # falsy -> skip
        "bad": "notadict",
    }), encoding="utf-8")
    store = _store(tmp_path, legacy=legacy)
    assert store.migrate_legacy() == 1
    seeded = store.get("us_open:2026-07-14")
    assert seeded["delivery_state"] == DELIVERY_SENT
    assert seeded["migrated_from_legacy"] is True
    assert seeded["status"] is None  # do not fabricate on_time
    assert store.get("us_open:2026-07-15") is None
    assert store.get("us_open:2026-07-16") is None


def test_migrate_legacy_is_idempotent(tmp_path):
    legacy = tmp_path / "brief_sent_today.json"
    legacy.write_text(json.dumps({"2026-07-14": {"us_open": True}}),
                      encoding="utf-8")
    store = _store(tmp_path, legacy=legacy)
    assert store.migrate_legacy() == 1
    assert store.migrate_legacy() == 0  # second run adds nothing


def test_migrate_legacy_no_file_is_noop(tmp_path):
    store = _store(tmp_path, legacy=tmp_path / "missing.json")
    assert store.migrate_legacy() == 0


# --- corruption / pruning ---------------------------------------------------

def test_corrupt_state_file_is_tolerated(tmp_path):
    path = tmp_path / "us_open_delivery_state.json"
    path.write_text("{not json", encoding="utf-8")
    store = UsOpenDeliveryStore(path)
    assert store.get("us_open:2026-07-20") is None
    store.upsert(_record(_session(2026, 7, 20, 21, 32)))
    assert store.get("us_open:2026-07-20") is not None


def test_old_sessions_pruned_relative_to_newest(tmp_path):
    store = _store(tmp_path)
    store.upsert(_record(_session(2026, 1, 1, 22, 32)))
    # 31 days later -> the January record ages past the 21-day retention.
    store.upsert(_record(_session(2026, 2, 1, 22, 32)))
    assert store.get("us_open:2026-01-01") is None
    assert store.get("us_open:2026-02-01") is not None


# --- public health surface --------------------------------------------------

def test_public_health_is_newest_first_and_leaks_no_secrets(tmp_path):
    store = _store(tmp_path)
    store.upsert(_record(_session(2026, 7, 20, 21, 32), delivery_state=DELIVERY_SENT))
    store.upsert(_record(_session(2026, 7, 21, 21, 32), delivery_state=DELIVERY_SENT))
    health = store.public_health()
    assert [h["session_date_et"] for h in health] == ["2026-07-21", "2026-07-20"]
    blob = json.dumps(health).lower()
    for forbidden in ("token", "chat_id", "bot", "position", "telegram"):
        assert forbidden not in blob
