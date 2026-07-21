"""Session-keyed delivery state for the U.S. opening brief.

Issue #13 / ``docs/market_brief_sla_v1.md`` section 4.

A boolean ``brief_sent_today.json`` marker cannot prove *where* delay happened
or guarantee at-most-once delivery. This module persists a per-session state
machine with explicit claim/sent/failed/ambiguous/skipped states, plus the
public-safe timing fields the incident review needed (expected/started/sent
timestamps, lateness, schedule source, stage code).

Reliability properties (repair round):

- Writes are atomic (temp file + fsync + ``os.replace``) so a reader never sees
  a partial file.
- A *missing* file is an empty state (legitimate first run); a *corrupt* file
  fails closed (``StateReadError``) so a lost record can never license a
  re-send.
- ``sent`` is never downgraded; ``failed`` / ``claimed`` are never silently
  overwritten by a lateral expiry that would erase the failure signal.
- Legacy migration is gated to the current ET session date so a legacy send
  that crossed Taipei midnight can never pre-mark a *future* real session.

The file only ever contains timestamps, session keys, statuses and generic
stage codes — never Telegram content, chat IDs, tokens or portfolio data — so
the committed ``data_store/us_open_delivery_state.json`` doubles as a
public-safe delivery-health surface.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

STATE_SCHEMA_VERSION = 1
STATE_PATH = Path("data_store/us_open_delivery_state.json")
LEGACY_DEDUP_PATH = Path("data_store/brief_sent_today.json")
BRIEF_TYPE = "us_open"

# Records older than this many days are pruned to bound file growth.
RETENTION_DAYS = 21
# Bounded per-session attempt-outcome telemetry (durable, not log-only).
MAX_ATTEMPT_LOG = 12

# delivery_state values (contract section 4, plus 'observing' for durable
# pre-open attempt telemetry).
DELIVERY_OBSERVING = "observing"  # pre-open / early attempt; non-terminal
DELIVERY_CLAIMED = "claimed"
DELIVERY_SENT = "sent"
DELIVERY_FAILED = "failed"
DELIVERY_AMBIGUOUS = "ambiguous"
DELIVERY_SKIPPED = "skipped"

# resolve_delivery_action outcomes.
DO_PROCEED = "proceed"  # no prior success; send now
DO_RETRY = "retry"  # prior attempt definitively failed; safe to resend
DO_SKIP_DUPLICATE = "skip_duplicate"  # already delivered this session
DO_SKIP_AMBIGUOUS = "skip_ambiguous"  # already surfaced as ambiguous; leave it
DO_AMBIGUOUS = "ambiguous"  # prior unresolved claim; surface, do not resend


class StateReadError(Exception):
    """Raised when an existing state file cannot be parsed (fail closed)."""


def resolve_delivery_action(existing: dict | None) -> str:
    """Decide what to do given the persisted record for this session.

    A persisted ``claimed`` state can only have been left by a *previous* run
    that crashed between persisting its (durable) claim and resolving the send.
    That is a genuine exactly-once ambiguity: we surface it rather than risk an
    uncontrolled duplicate (contract section 4).
    """
    if not existing:
        return DO_PROCEED
    state = existing.get("delivery_state")
    if state == DELIVERY_SENT:
        return DO_SKIP_DUPLICATE
    if state == DELIVERY_AMBIGUOUS:
        return DO_SKIP_AMBIGUOUS
    if state == DELIVERY_CLAIMED:
        return DO_AMBIGUOUS
    if state == DELIVERY_FAILED:
        return DO_RETRY
    # observing (pre-open) / skipped (wrong-session/expired) — a later in-window
    # attempt may still send.
    return DO_PROCEED


class UsOpenDeliveryStore:
    """Atomic, fail-closed reader/writer for the per-session delivery state."""

    def __init__(
        self,
        path: Path | str = STATE_PATH,
        legacy_path: Path | str | None = LEGACY_DEDUP_PATH,
    ) -> None:
        self.path = Path(path)
        self.legacy_path = Path(legacy_path) if legacy_path else None

    # -- raw io --------------------------------------------------------------

    def _read_raw(self) -> dict[str, Any]:
        if not self.path.exists():
            # A missing file is a legitimate empty state (first run ever).
            return {"schema_version": STATE_SCHEMA_VERSION, "sessions": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            # An *existing* but unreadable file must NOT be treated as empty:
            # a lost sent-record would license a duplicate send. Fail closed.
            raise StateReadError(
                f"{self.path} exists but is unreadable: {type(exc).__name__}"
            ) from exc
        if not isinstance(data, dict):
            raise StateReadError(f"{self.path} is not a JSON object")
        sessions = data.get("sessions")
        if not isinstance(sessions, dict):
            sessions = {}
        return {
            "schema_version": data.get("schema_version", STATE_SCHEMA_VERSION),
            "sessions": sessions,
        }

    def _write_raw(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        # Atomic write: fully materialise a temp file, fsync, then rename over
        # the target so a concurrent reader never observes a partial JSON.
        fd, tmp_name = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".us_open_state.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    @staticmethod
    def _prune(sessions: dict[str, Any]) -> None:
        # Prune relative to the newest record on hand, not the wall clock, so
        # pruning is deterministic and history-length bounded without coupling
        # tests (or replays) to the real date. In production the newest record
        # is ~today, so stale sessions still age out.
        parsed_dates = [
            d
            for d in (
                _parse_iso_date(record.get("session_date_et"))
                for record in sessions.values()
                if isinstance(record, dict)
            )
            if d is not None
        ]
        if not parsed_dates:
            return
        cutoff = max(parsed_dates) - timedelta(days=RETENTION_DAYS)
        for key in list(sessions.keys()):
            record = sessions.get(key)
            parsed = (
                _parse_iso_date(record.get("session_date_et"))
                if isinstance(record, dict)
                else None
            )
            if parsed is not None and parsed < cutoff:
                sessions.pop(key, None)

    # -- reads ---------------------------------------------------------------

    def get(self, session_key: str) -> dict | None:
        return self._read_raw()["sessions"].get(session_key)

    def public_health(self, limit: int = 10) -> list[dict]:
        """Return recent session records, newest first (already public-safe)."""
        sessions = self._read_raw()["sessions"]
        ordered = sorted(
            sessions.values(),
            key=lambda rec: rec.get("session_date_et") or "",
            reverse=True,
        )
        return ordered[:limit]

    # -- writes --------------------------------------------------------------

    def upsert(self, record: dict) -> dict:
        """Merge ``record`` into the persisted state and return what was kept.

        The disk is re-read on every write, so concurrent records for *other*
        sessions are never clobbered (models the state-write conflict / rebase
        case). Downgrade protection:

        - a durable ``sent`` is never replaced by a lower state — a Telegram
          success that raced a state write is not lost;
        - a ``failed`` or ``claimed`` record is never silently overwritten by an
          expiry ``skipped`` that would erase the failure/ambiguity signal
          (callers must set an explicit ``expired_after_*`` stage instead).
        """
        key = record["session_key"]
        data = self._read_raw()
        sessions = data["sessions"]
        disk = sessions.get(key)
        if isinstance(disk, dict):
            disk_state = disk.get("delivery_state")
            new_state = record.get("delivery_state")
            if disk_state == DELIVERY_SENT and new_state != DELIVERY_SENT:
                return disk
            # Defensive: never let an expiry (skipped) silently erase a prior
            # never-delivered failure. An expired-after-failure must be recorded
            # as 'failed' (status=expired), keeping the failure stage_code.
            if disk_state == DELIVERY_FAILED and new_state == DELIVERY_SKIPPED:
                return disk
        sessions[key] = record
        self._prune(sessions)
        data["schema_version"] = STATE_SCHEMA_VERSION
        self._write_raw(data)
        return record

    # -- legacy migration ----------------------------------------------------

    def migrate_legacy(self, max_session_date_et: str | None = None) -> int:
        """Seed ``sent`` records from the legacy boolean dedup file.

        For ``us_open`` the exchange-open Taipei date normally equals the ET
        session date, so a legacy ``brief_sent_today[<date>].us_open == true``
        maps to session key ``us_open:<date>``. But the legacy marker keys by
        *send* time, and a badly delayed send could cross Taipei midnight and be
        keyed to the next date. To ensure that can never pre-mark a *future*
        real session as delivered, migration is gated to
        ``max_session_date_et`` (the current ET session date). Idempotent.
        """
        if not self.legacy_path or not self.legacy_path.exists():
            return 0
        try:
            legacy = json.loads(self.legacy_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            return 0
        if not isinstance(legacy, dict):
            return 0

        max_date = _parse_iso_date(max_session_date_et)
        data = self._read_raw()
        sessions = data["sessions"]
        migrated = 0
        for taipei_date, marks in legacy.items():
            if not isinstance(marks, dict) or not marks.get(BRIEF_TYPE):
                continue
            parsed = _parse_iso_date(taipei_date)
            # Never seed a session dated after the current ET session: a legacy
            # entry keyed one day past its open must not skip a real future open.
            if max_date is not None and parsed is not None and parsed > max_date:
                continue
            key = f"{BRIEF_TYPE}:{taipei_date}"
            if key in sessions:
                continue
            sessions[key] = {
                "schema_version": STATE_SCHEMA_VERSION,
                "brief_type": BRIEF_TYPE,
                "session_date_et": taipei_date,
                "session_key": key,
                "expected_at_taipei": None,
                "workflow_started_at": None,
                "runner_started_at": None,
                "generation_started_at": None,
                "generation_finished_at": None,
                "sent_at": None,
                # Legacy boolean carried no timestamps; do not fabricate a
                # status. Only the fact of delivery is known.
                "lateness_minutes": None,
                "schedule_source": "legacy_boolean_migration",
                "workflow_run_id": None,
                "delivery_state": DELIVERY_SENT,
                "status": None,
                "stage_code": "legacy_boolean_migrated",
                "migrated_from_legacy": True,
            }
            migrated += 1
        if migrated:
            self._prune(sessions)
            data["schema_version"] = STATE_SCHEMA_VERSION
            self._write_raw(data)
        return migrated


def _parse_iso_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def record_attempt(record: dict, outcome: str, stage_code: str | None) -> None:
    """Append a compact, bounded attempt-outcome entry for durable telemetry."""
    log = record.get("observed_attempts")
    if not isinstance(log, list):
        log = []
    log.append({"outcome": outcome, "stage_code": stage_code})
    record["observed_attempts"] = log[-MAX_ATTEMPT_LOG:]


def new_record(
    session,
    *,
    status: str | None,
    lateness_minutes: int | None,
    schedule_source: str,
    workflow_run_id: str,
    workflow_started_at: str | None,
    runner_started_at: str | None = None,
    delivery_state: str = DELIVERY_CLAIMED,
) -> dict:
    """Build a fresh delivery record for a session (contract section 4 schema).

    ``workflow_started_at`` is the real workflow first-step time (before Python
    setup/install) so GitHub queue delay can be separated from runner/setup and
    generation delay; ``runner_started_at`` is when the Python attempt began.
    """
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "brief_type": BRIEF_TYPE,
        "session_date_et": session.session_date_et,
        "session_key": session.session_key,
        "expected_at_taipei": session.open_at_taipei.isoformat(),
        "workflow_started_at": workflow_started_at,
        "runner_started_at": runner_started_at,
        "generation_started_at": None,
        "generation_finished_at": None,
        "sent_at": None,
        "lateness_minutes": lateness_minutes,
        "schedule_source": schedule_source,
        "workflow_run_id": workflow_run_id,
        "delivery_state": delivery_state,
        "status": status,
        "stage_code": None,
        "observed_attempts": [],
    }
