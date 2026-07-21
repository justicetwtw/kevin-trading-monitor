"""Authoritative-remote durability for the Trump delivery ledger and archive.

Mirrors the merged ``us_open`` remote-state hardening, isolated to the Trump
per-post semantics:

- Before any non-idempotent Telegram send the runner **hydrates** the local
  ledger AND the rolling archive from ``origin/main`` — a stale event checkout (a
  queued scheduled run or a GitHub re-run started from a SHA predating the
  previous run's state commit) can otherwise show a post as unseen and re-blast
  it, or clobber origin's archive with an older copy.
- New archive rows are committed + pushed + **verified on origin BEFORE any
  per-post claim/send** (``durable_push_capture``), so a remote ``sent`` record
  can never exist without the corresponding post already durable in the
  authoritative archive.
- Each per-post ``claimed`` / terminal transition is committed, pushed, and then
  **verified on origin** (compare-and-set on ``post_id`` + unique
  ``workflow_attempt_id``) before the outbound send is trusted as durable.
- Every push stages the whole ``data_store/`` directory, so an unstaged archive
  change can never leave the working tree dirty and abort the ledger
  ``git pull --rebase`` (which refuses on unstaged changes).
- Every remote payload is read through the shared fail-closed validators; a
  malformed authoritative ledger/archive maps to a controlled red / no-send,
  never a silent empty base or an uncaught throw.

Durable mode is gated by ``TRUMP_DURABLE_STATE=1`` (set only in the workflow).
Off locally and in tests, hydration is a no-op and pushes report ``disabled`` so
the runner relies on the trailing ``commit-state`` action exactly as before — no
git side effects in unit tests.

The ledger only ever contains post IDs, states, timestamps, source names and
generic stage codes — never translation text, chat IDs or tokens. The archive
holds the captured public post payloads (as it always has).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable

from loguru import logger

from src.storage.trump_delivery_state import (
    DELIVERY_AMBIGUOUS,
    DELIVERY_CLAIMED,
    DELIVERY_SENT,
    StateReadError,
    TrumpDeliveryStore,
)

# Durable-push outcomes.
PUSH_DISABLED = "disabled"  # durable mode off (local/tests): rely on commit-state
PUSH_OK = "pushed"  # claim/result is durable and verified on shared state
PUSH_FAILED = "failed"  # durable mode on but the record could not be verified
PUSH_CONFLICT_SENT = "conflict_sent"  # another attempt already DELIVERED this post
PUSH_CONFLICT_CLAIM = "conflict_claim"  # another attempt holds an unresolved claim

_ENABLE_ENV = "TRUMP_DURABLE_STATE"
_BRANCH_ENV = "TRUMP_STATE_BRANCH"

# Paths AS TRACKED IN THE REPO (repo-root-relative). ``git show <ref>:<path>`` and
# ``git ls-tree <ref> -- <path>`` require repo-relative paths, not the store's
# absolute local path. Durable mode only runs where the working directory is the
# repo root, so these resolve to the same files the store/archive read and write.
_STATE_REL = "data_store/trump_delivery_state.json"
_ARCHIVE_REL = "data_store/trump_posts_archive.json"
_LEGACY_REL = "data_store/trump_seen_posts.json"
_DATA_STORE_REL = "data_store"


def durable_enabled() -> bool:
    return os.getenv(_ENABLE_ENV) == "1"


def _branch() -> str:
    return os.getenv(_BRANCH_ENV, "main")


def _git_run(*args):
    """Run one git subprocess (CI-only; patched in unit tests)."""
    import subprocess

    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=False
    )


def _sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)


# -- ledger helpers ----------------------------------------------------------


def _remote_record(content: str, post_id: str) -> dict | None:
    """Look up one post's record in remote ledger via the SHARED fail-closed
    validator, so hydration, the claim CAS and post-push verification all
    interpret origin identically. Raises ``StateReadError`` on a malformed
    payload; returns ``None`` only when the state is valid but has no such post.
    """
    posts = TrumpDeliveryStore.parse_state(
        content, origin="origin/main state"
    )["posts"]
    record = posts.get(str(post_id))
    return record if isinstance(record, dict) else None


def _remote_state_has(content: str, expected: dict) -> bool:
    """True iff origin has ``expected`` post record with OUR attempt identity.

    Identity is matched on ``workflow_attempt_id`` (run id + run attempt), not
    the reused ``run_id``, so a re-run cannot verify a prior attempt's record.
    Raises ``StateReadError`` on a malformed remote payload.
    """
    record = _remote_record(content, expected["post_id"])
    if record is None:
        return False
    return (
        record.get("delivery_state") == expected["delivery_state"]
        and record.get("workflow_attempt_id") == expected.get("workflow_attempt_id")
    )


def _remote_conflict_kind(content: str, expected: dict) -> str | None:
    """Classify a compare-and-set conflict against origin's validated ledger.

    ``PUSH_CONFLICT_SENT`` if origin already shows this post delivered (by any
    attempt); ``PUSH_CONFLICT_CLAIM`` if a *different* attempt holds an
    unresolved ``claimed``/``ambiguous`` record; else ``None``. Raises
    ``StateReadError`` on a malformed remote.
    """
    record = _remote_record(content, expected["post_id"])
    if record is None:
        return None
    state = record.get("delivery_state")
    if state == DELIVERY_SENT:
        return PUSH_CONFLICT_SENT
    if state in (DELIVERY_CLAIMED, DELIVERY_AMBIGUOUS):
        if record.get("workflow_attempt_id") != expected.get("workflow_attempt_id"):
            return PUSH_CONFLICT_CLAIM
    return None


# -- archive helpers ---------------------------------------------------------


def _parse_archive(content: str, *, origin: str) -> dict:
    """Parse + validate a remote archive payload (fail closed, key==id bound)."""
    from src.data.trump_truth import ArchiveError, validate_archive_content

    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise StateReadError(
            f"{origin} archive is unreadable: {type(exc).__name__}"
        ) from exc
    try:
        return validate_archive_content(data, origin=origin)
    except ArchiveError as exc:
        raise StateReadError(str(exc)) from exc


def _remote_archive_has(content: str, post_ids: Iterable[str]) -> bool:
    """True iff origin's archive contains every required post id.

    A malformed remote archive here cannot prove durability, so it is treated as
    not-yet-durable (retry / fail), never an uncaught throw.
    """
    try:
        data = _parse_archive(content, origin="origin/main")
    except StateReadError:
        return False
    return all(str(pid) in data for pid in post_ids)


def _write_local_archive(content: str) -> None:
    """Validate origin's archive and atomically make it the local base."""
    from src.data.trump_truth import ARCHIVE_FILE
    from src.storage import state_manager

    data = _parse_archive(content, origin="origin/main")
    if not state_manager.write_json(ARCHIVE_FILE, data):
        raise StateReadError("failed to persist hydrated archive locally")


def _write_empty_archive() -> None:
    """Reset the local archive to empty (verified-absent remote bootstrap)."""
    from src.data.trump_truth import ARCHIVE_FILE
    from src.storage import state_manager

    if not state_manager.write_json(ARCHIVE_FILE, {}):
        raise StateReadError("failed to reset local archive to empty")


# -- absence / hydration -----------------------------------------------------


def _remote_path_absent(path: str, branch: str) -> bool:
    """True only if ``path`` is PROVABLY absent from ``origin/<branch>``.

    ``git ls-tree`` exits 0 with empty output only when the path does not exist
    in the tree; any non-zero result, or a listed entry, is NOT proof of absence.
    A genuine first-ever run can bootstrap, while a transient/unreadable object
    (which must fail closed) is never mistaken for "no file yet".
    """
    result = _git_run("ls-tree", f"origin/{branch}", "--", path)
    return result.returncode == 0 and not (result.stdout or "").strip()


def hydrate_from_remote(store: TrumpDeliveryStore) -> bool:
    """Replace the local ledger with origin's authoritative version.

    Returns ``True`` only on a VERIFIED-absent remote ledger (a genuine first
    run, i.e. a bootstrap); ``False`` when it hydrated from present remote content
    or when durable mode is off. On verified absence the local ledger is reset to
    an explicit empty state so a stale local tracked file from an older event
    checkout can never seed a decision. Fails closed (``StateReadError``) if
    origin cannot be fetched, if the object is unreadable while the path is not
    provably absent, or if the remote state is malformed.
    """
    if not durable_enabled():
        return False
    branch = _branch()
    if _git_run("fetch", "origin", branch).returncode != 0:
        raise StateReadError("cannot fetch origin to hydrate authoritative ledger")
    show = _git_run("show", f"origin/{branch}:{_STATE_REL}")
    if show.returncode == 0:
        store.hydrate_from(show.stdout or "")
        return False
    if _remote_path_absent(_STATE_REL, branch):
        store.reset_empty()  # authoritative empty base; discard any stale local
        return True
    raise StateReadError(
        "authoritative remote ledger could not be read (path present but "
        "unreadable); failing closed"
    )


def hydrate_archive_from_remote() -> bool:
    """Replace the local rolling archive with origin's authoritative version.

    So a stale checkout never re-writes an older archive over origin's (which
    would drop recently-captured rows) and the pre-send capture push rebases
    cleanly. On verified absence the local archive is reset to empty. Same
    fail-closed rules as the ledger hydration.
    """
    if not durable_enabled():
        return False
    branch = _branch()
    if _git_run("fetch", "origin", branch).returncode != 0:
        raise StateReadError("cannot fetch origin to hydrate authoritative archive")
    show = _git_run("show", f"origin/{branch}:{_ARCHIVE_REL}")
    if show.returncode == 0:
        _write_local_archive(show.stdout or "")
        return False
    if _remote_path_absent(_ARCHIVE_REL, branch):
        _write_empty_archive()  # authoritative empty base; discard stale local
        return True  # no archive on origin yet (genuine first run)
    raise StateReadError(
        "authoritative remote archive could not be read (path present but "
        "unreadable); failing closed"
    )


def hydrate_legacy_from_remote(legacy_path) -> bool:
    """Make the local legacy seen file authoritative from ``origin/main``.

    First-ledger bootstrap migrates ``trump_seen_posts.json``; a stale event
    checkout could carry an OLDER legacy-seen than origin (e.g. a queued new-code
    run behind an old-code run that just committed newer seen state), which would
    re-blast posts the old run already delivered. Reading the legacy file from
    validated ``origin/main`` — resetting the local copy to origin's content, or
    to empty when origin has none — closes that rollout window. No-op when durable
    mode is off (local/tests keep their own legacy file).
    """
    if not durable_enabled() or not legacy_path:
        return False
    from pathlib import Path

    branch = _branch()
    legacy = Path(str(legacy_path))
    if _git_run("fetch", "origin", branch).returncode != 0:
        raise StateReadError("cannot fetch origin to hydrate authoritative legacy")
    show = _git_run("show", f"origin/{branch}:{_LEGACY_REL}")
    if show.returncode == 0:
        try:
            data = json.loads(show.stdout or "{}")
        except (json.JSONDecodeError, ValueError) as exc:
            raise StateReadError(
                f"origin legacy seen malformed: {type(exc).__name__}"
            ) from exc
        if not isinstance(data, dict):
            raise StateReadError("origin legacy seen is not a JSON object")
    elif _remote_path_absent(_LEGACY_REL, branch):
        data = {}  # origin has no legacy seen: authoritative empty
    else:
        raise StateReadError(
            "authoritative remote legacy seen unreadable; failing closed"
        )
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return True


# -- shared commit / push / verify core --------------------------------------


def _commit_push_verify(message, *, verify, cas=None) -> str:
    """Stage the whole ``data_store/``, commit, rebase, push, verify on origin.

    Staging the whole directory (not just the ledger) keeps the working tree
    clean before ``git pull --rebase`` — an unstaged archive change would
    otherwise abort the rebase — and pushes the ledger and archive in one
    transaction. ``verify(branch) -> bool`` proves durability from origin's
    CONTENT (raising ``StateReadError`` => not durable). ``cas(ledger_content)``,
    when given, guards the initial claim: it returns a conflict outcome, ``None``
    to proceed, or raises ``StateReadError`` to fail closed.
    """
    branch = _branch()

    def _ok(*args) -> bool:
        return _git_run(*args).returncode == 0

    _git_run("config", "user.name", "github-actions[bot]")
    _git_run(
        "config", "user.email", "github-actions[bot]@users.noreply.github.com"
    )

    for attempt in range(1, 5):
        if attempt > 1:
            _sleep((attempt - 1) * 2)
        if not _ok("fetch", "origin", branch):
            continue
        if cas is not None:
            pre = _git_run("show", f"origin/{branch}:{_STATE_REL}")
            if pre.returncode == 0:
                try:
                    conflict = cas(pre.stdout or "")
                except StateReadError:
                    logger.error(
                        "trump CAS pre-read: authoritative remote ledger is "
                        "malformed; failing closed (no claim, no send)"
                    )
                    return PUSH_FAILED
                if conflict is not None:
                    return conflict
            elif not _remote_path_absent(_STATE_REL, branch):
                # Cannot read the pre-claim remote and the path is not provably
                # absent: do NOT add/commit/pull/push on a stale base.
                continue
        # Stage the whole data_store dir so nothing (esp. the archive) is left
        # unstaged to abort the rebase. Missing files under the dir are fine.
        _git_run("add", "--", _DATA_STORE_REL)
        staged_empty = _git_run("diff", "--cached", "--quiet").returncode == 0
        if not staged_empty:
            if not _ok("commit", "-m", message):
                continue
        # ALWAYS reconcile with the freshly-fetched origin before pushing (even a
        # clean index on a retry) so a benign non-fast-forward race recovers.
        if not _ok("pull", "--rebase", "origin", branch):
            _git_run("rebase", "--abort")
            continue
        _git_run("push", "origin", f"HEAD:{branch}")
        # Proof of durability is the REMOTE CONTENT, not the push exit code.
        if not _ok("fetch", "origin", branch):
            continue
        try:
            if verify(branch):
                return PUSH_OK
        except StateReadError:
            pass
    logger.error("trump durable push could not verify on origin")
    return PUSH_FAILED


def durable_push(
    store: TrumpDeliveryStore,
    message: str,
    *,
    expected: dict,
    block_foreign_claim: bool = False,
) -> str:
    """Commit + push the ledger (with the archive) and VERIFY the record on origin.

    ``expected`` = {post_id, delivery_state, workflow_attempt_id}. Returns
    ``PUSH_OK`` only after re-fetching origin and confirming its ledger has a
    record for this post with OUR ``delivery_state`` and ``workflow_attempt_id``.
    With ``block_foreign_claim`` (the initial claim), a remote ``sent`` →
    ``PUSH_CONFLICT_SENT`` and a foreign ``claimed``/``ambiguous`` →
    ``PUSH_CONFLICT_CLAIM`` so a re-run never steals a prior attempt's post.
    """
    if not durable_enabled():
        return PUSH_DISABLED

    cas = None
    if block_foreign_claim:
        cas = lambda content: _remote_conflict_kind(content, expected)  # noqa: E731

    def verify(branch: str) -> bool:
        show = _git_run("show", f"origin/{branch}:{_STATE_REL}")
        if show.returncode != 0:
            return False
        return _remote_state_has(show.stdout or "", expected)

    return _commit_push_verify(message, verify=verify, cas=cas)


def _remote_ledger_has_records(content: str, post_ids: Iterable[str]) -> bool:
    """True iff origin's ledger has a record for every ``post_ids`` entry."""
    try:
        posts = TrumpDeliveryStore.parse_state(
            content, origin="origin/main state"
        )["posts"]
    except StateReadError:
        return False
    return all(str(pid) in posts for pid in post_ids)


def durable_push_capture(post_ids: Iterable[str], message: str) -> str:
    """Commit + push the capture (archive rows + pending ledger records) and
    VERIFY both on origin.

    Called BEFORE any per-post claim/send, so a remote ``sent`` record can never
    exist without the post already durable in the authoritative archive, AND a
    timeout before a post's per-post claim cannot leave it archive-only with no
    ledger record. Returns ``PUSH_OK`` only when origin's archive AND ledger both
    contain every ``post_ids`` entry.
    """
    if not durable_enabled():
        return PUSH_DISABLED
    ids = [str(p) for p in post_ids]

    def verify(branch: str) -> bool:
        archive = _git_run("show", f"origin/{branch}:{_ARCHIVE_REL}")
        ledger = _git_run("show", f"origin/{branch}:{_STATE_REL}")
        if archive.returncode != 0 or ledger.returncode != 0:
            return False
        return _remote_archive_has(archive.stdout or "", ids) and (
            _remote_ledger_has_records(ledger.stdout or "", ids)
        )

    return _commit_push_verify(message, verify=verify)
