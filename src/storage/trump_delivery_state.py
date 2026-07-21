"""Durable, exactly-once delivery ledger for Trump Truth Social posts.

A boolean ``trump_seen_posts.json`` (delivered == seen) cannot express partial
delivery: if a post reached recipient 1 but a later recipient/fragment failed or
the run was cancelled, marking it unseen makes the next run re-blast the whole
chunk to every recipient (duplicating recipient 1); marking it seen loses the
undelivered recipients. This ledger records a per-post delivery state machine so
an ambiguous/partial outbound is *quarantined*, never blindly auto-retried.

Modeled on the hardened ``us_open_state`` machinery (contract §4):

- Writes are atomic (temp file + fsync + ``os.replace``) so a reader never sees
  a partial file and a SIGKILL mid-write cannot truncate the ledger.
- A *missing* file is an empty state (legitimate first run); a *corrupt* file
  fails closed (``StateReadError``) so a lost record can never license a
  duplicate blast of the whole checkpoint window.
- ``sent`` is terminal and never downgraded; a durable ``claimed`` left by a
  crashed run resolves to ``ambiguous`` (surface, do not resend), not to
  ordinary unseen.
- The capture checkpoint lives here too, so a corrupt health file can no longer
  silently reset the eligible window to the 24h backfill.

The file only ever contains post IDs, timestamps, source names, statuses and
generic stage codes — never post text, translation text, chat IDs or tokens —
so the committed ``data_store/trump_delivery_state.json`` is a public-safe
delivery-health surface.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

DATA_STORE_DIR = Path(__file__).resolve().parents[2] / "data_store"
STATE_PATH = DATA_STORE_DIR / "trump_delivery_state.json"
LEGACY_SEEN_PATH = DATA_STORE_DIR / "trump_seen_posts.json"

STATE_SCHEMA_VERSION = 1
# Bound file growth; keep the most recent posts by resolution/claim time.
MAX_POSTS = 10000

# delivery_state values.
DELIVERY_CLAIMED = "claimed"
DELIVERY_SENT = "sent"
DELIVERY_FAILED = "failed"
DELIVERY_AMBIGUOUS = "ambiguous"

SUPPORTED_DELIVERY_STATES = frozenset(
    {DELIVERY_CLAIMED, DELIVERY_SENT, DELIVERY_FAILED, DELIVERY_AMBIGUOUS}
)

# resolve_delivery_action outcomes.
DO_PROCEED = "proceed"  # never attempted -> send now
DO_RETRY = "retry"  # prior attempt definitively failed (nothing delivered)
DO_SKIP_SENT = "skip_sent"  # already delivered
DO_SKIP_AMBIGUOUS = "skip_ambiguous"  # already quarantined; leave it
DO_AMBIGUOUS = "ambiguous"  # prior unresolved claim -> quarantine, do not resend


class StateReadError(Exception):
    """Raised when an existing ledger cannot be parsed (fail closed)."""


def resolve_delivery_action(existing: dict | None) -> str:
    """Decide what to do for a post given its persisted record.

    A persisted ``claimed`` can only have been left by a previous run that
    crashed between persisting its durable claim and resolving the send — a
    genuine exactly-once ambiguity we surface rather than risk a duplicate.
    """
    if not existing:
        return DO_PROCEED
    state = existing.get("delivery_state")
    if state == DELIVERY_SENT:
        return DO_SKIP_SENT
    if state == DELIVERY_AMBIGUOUS:
        return DO_SKIP_AMBIGUOUS
    if state == DELIVERY_CLAIMED:
        return DO_AMBIGUOUS
    if state == DELIVERY_FAILED:
        return DO_RETRY
    return DO_PROCEED


class TrumpDeliveryStore:
    """Atomic, fail-closed reader/writer for the per-post delivery ledger."""

    def __init__(
        self,
        path: Path | str = STATE_PATH,
        legacy_path: Path | str | None = LEGACY_SEEN_PATH,
    ) -> None:
        self.path = Path(path)
        self.legacy_path = Path(legacy_path) if legacy_path else None

    # -- raw io --------------------------------------------------------------

    @staticmethod
    def parse_state(content: str, *, origin: str = "state") -> dict[str, Any]:
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            raise StateReadError(
                f"{origin} is unreadable: {type(exc).__name__}"
            ) from exc
        if not isinstance(data, dict):
            raise StateReadError(f"{origin} is not a JSON object")
        schema = data.get("schema_version", STATE_SCHEMA_VERSION)
        if not isinstance(schema, int) or schema > STATE_SCHEMA_VERSION:
            raise StateReadError(f"{origin} has unsupported schema_version {schema!r}")
        posts = data.get("posts")
        if not isinstance(posts, dict):
            raise StateReadError(f"{origin} has a missing/invalid 'posts' object")
        for key, record in posts.items():
            if not isinstance(record, dict):
                raise StateReadError(f"{origin} post {key!r} is not an object")
            if record.get("delivery_state") not in SUPPORTED_DELIVERY_STATES:
                raise StateReadError(
                    f"{origin} post {key!r} has unsupported delivery_state "
                    f"{record.get('delivery_state')!r}"
                )
        return {
            "schema_version": schema,
            "capture_started_at": data.get("capture_started_at"),
            "posts": posts,
        }

    def _read_raw(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "schema_version": STATE_SCHEMA_VERSION,
                "capture_started_at": None,
                "posts": {},
            }
        try:
            text = self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise StateReadError(
                f"{self.path} exists but is unreadable: {type(exc).__name__}"
            ) from exc
        return self.parse_state(text, origin=str(self.path))

    def _write_raw(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".trump_delivery.", suffix=".tmp"
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
    def _prune(posts: dict[str, Any]) -> None:
        if len(posts) <= MAX_POSTS:
            return
        ordered = sorted(
            posts.items(),
            key=lambda item: str(
                item[1].get("resolved_at")
                or item[1].get("claimed_at")
                or item[1].get("created_at")
                or ""
            ),
        )
        for key, _ in ordered[: len(posts) - MAX_POSTS]:
            posts.pop(key, None)

    # -- reads ---------------------------------------------------------------

    def get(self, post_id: str) -> dict | None:
        return self._read_raw()["posts"].get(str(post_id))

    def action_for(self, post_id: str) -> str:
        return resolve_delivery_action(self.get(post_id))

    def capture_started_at(self) -> str | None:
        return self._read_raw().get("capture_started_at")

    def set_capture_started_at(self, value: str) -> None:
        data = self._read_raw()
        if data.get("capture_started_at") == value:
            return
        data["capture_started_at"] = value
        data["schema_version"] = STATE_SCHEMA_VERSION
        self._write_raw(data)

    def health_counts(self) -> dict[str, int]:
        posts = self._read_raw()["posts"]
        counts = {state: 0 for state in SUPPORTED_DELIVERY_STATES}
        for record in posts.values():
            state = record.get("delivery_state")
            if state in counts:
                counts[state] += 1
        return counts

    # -- writes --------------------------------------------------------------

    def claim(self, post: dict, *, run_id: str | None = None) -> dict | None:
        """Durably record a ``claimed`` state before a non-idempotent send.

        Returns the persisted record, or ``None`` when the post is already
        ``sent`` (never re-claim/downgrade a delivered post).
        """
        post_id = str(post.get("id") or "")
        if not post_id:
            return None
        data = self._read_raw()
        posts = data["posts"]
        disk = posts.get(post_id)
        if isinstance(disk, dict) and disk.get("delivery_state") == DELIVERY_SENT:
            return None
        record = {
            "post_id": post_id,
            "created_at": post.get("created_at"),
            "source": post.get("source"),
            "delivery_state": DELIVERY_CLAIMED,
            "claimed_at": _utc_now(),
            "resolved_at": None,
            "run_id": run_id,
            "stage_code": "claimed_before_send",
        }
        posts[post_id] = record
        self._prune(posts)
        data["schema_version"] = STATE_SCHEMA_VERSION
        self._write_raw(data)
        return record

    def resolve(
        self,
        post_id: str,
        outcome: str,
        *,
        stage_code: str | None = None,
        run_id: str | None = None,
    ) -> dict | None:
        """Persist a terminal-ish delivery outcome for a claimed post.

        ``sent`` is never downgraded. ``failed`` means nothing was delivered and
        a retry is safe; ``ambiguous`` means a partial/unknown outbound and must
        never be auto-retried.
        """
        post_id = str(post_id)
        state = {
            "sent": DELIVERY_SENT,
            "failed": DELIVERY_FAILED,
            "ambiguous": DELIVERY_AMBIGUOUS,
        }.get(outcome, DELIVERY_AMBIGUOUS)
        data = self._read_raw()
        posts = data["posts"]
        disk = posts.get(post_id)
        if isinstance(disk, dict) and disk.get("delivery_state") == DELIVERY_SENT:
            return disk  # never downgrade a durable success
        record = disk if isinstance(disk, dict) else {"post_id": post_id}
        record["delivery_state"] = state
        record["resolved_at"] = _utc_now()
        if run_id is not None:
            record["run_id"] = run_id
        record["stage_code"] = stage_code or f"resolved_{outcome}"
        posts[post_id] = record
        self._prune(posts)
        data["schema_version"] = STATE_SCHEMA_VERSION
        self._write_raw(data)
        return record

    # -- legacy migration ----------------------------------------------------

    def migrate_legacy_seen(self) -> int:
        """Seed ``sent`` records from the legacy boolean seen file (idempotent).

        The legacy file only proves a post was previously delivered; that maps
        to a terminal ``sent`` so a migrated post is never redelivered.
        """
        if not self.legacy_path or not self.legacy_path.exists():
            return 0
        try:
            legacy = json.loads(self.legacy_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            return 0
        if not isinstance(legacy, dict):
            return 0
        data = self._read_raw()
        posts = data["posts"]
        migrated = 0
        for post_id, meta in legacy.items():
            key = str(post_id)
            if not key or key in posts:
                continue
            created = meta.get("created_at") if isinstance(meta, dict) else None
            source = meta.get("source") if isinstance(meta, dict) else None
            posts[key] = {
                "post_id": key,
                "created_at": created,
                "source": source,
                "delivery_state": DELIVERY_SENT,
                "claimed_at": None,
                "resolved_at": meta.get("seen_at") if isinstance(meta, dict) else None,
                "run_id": None,
                "stage_code": "legacy_seen_migrated",
            }
            migrated += 1
        if migrated:
            self._prune(posts)
            data["schema_version"] = STATE_SCHEMA_VERSION
            self._write_raw(data)
        return migrated


def _utc_now() -> str:
    # Imported lazily so the module stays import-safe and testable; the runner
    # passes real timestamps through claim/resolve stage codes only.
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
