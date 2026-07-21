"""Authoritative-remote durability for the Trump delivery ledger.

Mirrors the merged ``us_open`` remote-state hardening, isolated to the Trump
ledger's per-post semantics:

- Before any non-idempotent Telegram send the runner **hydrates** the local
  ledger from ``origin/main`` — a stale event checkout (a queued scheduled run
  or a GitHub re-run started from a SHA predating the previous run's state
  commit) can otherwise show a post as unseen and re-blast it.
- Each per-post ``claimed`` / terminal transition is committed, pushed, and then
  **verified on origin** (compare-and-set on ``post_id`` + unique
  ``workflow_attempt_id``) BEFORE the outbound send is trusted as durable.
- Every remote payload is read through the shared fail-closed
  ``TrumpDeliveryStore.parse_state``; a malformed authoritative ledger maps to a
  controlled red / no-send, never a silent empty base or an uncaught throw.

Durable mode is gated by ``TRUMP_DURABLE_STATE=1`` (set only in the workflow).
Off locally and in tests, hydration is a no-op and pushes report ``disabled`` so
the runner relies on the trailing ``commit-state`` action exactly as before — no
git side effects in unit tests.

The pushed file only ever contains post IDs, states, timestamps, source names
and generic stage codes — never post text, translation text, chat IDs or tokens.
"""

from __future__ import annotations

import os

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

# Path AS TRACKED IN THE REPO (repo-root-relative). ``git show <ref>:<path>`` and
# ``git ls-tree <ref> -- <path>`` require the repo-relative path, not the store's
# absolute local path. Durable mode only runs in CI, where the working directory
# is the repo root and this resolves to the same file the store reads/writes.
_STATE_REL = "data_store/trump_delivery_state.json"


def durable_enabled() -> bool:
    return os.getenv(_ENABLE_ENV) == "1"


def _branch() -> str:
    return os.getenv(_BRANCH_ENV, "main")


def _git_run(*args):
    """Run one git subprocess (CI-only; patched in tests)."""
    import subprocess

    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=False
    )


def _sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)


def _remote_record(content: str, post_id: str) -> dict | None:
    """Look up one post's record in remote state via the SHARED fail-closed
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
    Raises ``StateReadError`` on a malformed remote payload (an unverifiable
    remote is treated as not-yet-durable by the caller).
    """
    record = _remote_record(content, expected["post_id"])
    if record is None:
        return False
    return (
        record.get("delivery_state") == expected["delivery_state"]
        and record.get("workflow_attempt_id") == expected.get("workflow_attempt_id")
    )


def _remote_conflict_kind(content: str, expected: dict) -> str | None:
    """Classify a compare-and-set conflict against origin's validated state.

    ``PUSH_CONFLICT_SENT`` if origin already shows this post delivered (by any
    attempt); ``PUSH_CONFLICT_CLAIM`` if a *different* attempt holds an
    unresolved ``claimed``/``ambiguous`` record; else ``None`` (no record, or our
    own attempt's record). Raises ``StateReadError`` on a malformed remote.
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


def _remote_path_absent(branch: str) -> bool:
    """True only if the ledger is PROVABLY absent from ``origin/<branch>``.

    ``git ls-tree`` exits 0 with empty output only when the path does not exist
    in the tree; any non-zero result, or a listed entry, is NOT proof of absence.
    A genuine first-ever run can bootstrap, while a transient/unreadable object
    (which must fail closed) is never mistaken for "no ledger yet".
    """
    result = _git_run("ls-tree", f"origin/{branch}", "--", _STATE_REL)
    return result.returncode == 0 and not (result.stdout or "").strip()


def hydrate_from_remote(store: TrumpDeliveryStore) -> bool:
    """Replace the local ledger with origin's authoritative version.

    No-op (returns ``False``) when durable mode is off. Otherwise fetches origin,
    reads ``origin/<branch>:<ledger>`` and validates it with the shared
    fail-closed rules. Fails closed (``StateReadError``) if origin cannot be
    fetched, if the object cannot be read while the path is not PROVABLY absent
    (a transient/unreadable object must never be read as "first run ever"), or if
    the remote state is malformed. Only a verified-absent path bootstraps a
    genuine first run.
    """
    if not durable_enabled():
        return False
    branch = _branch()
    if _git_run("fetch", "origin", branch).returncode != 0:
        raise StateReadError("cannot fetch origin to hydrate authoritative ledger")
    show = _git_run("show", f"origin/{branch}:{_STATE_REL}")
    if show.returncode == 0:
        store.hydrate_from(show.stdout or "")
        return True
    if _remote_path_absent(branch):
        return True
    raise StateReadError(
        "authoritative remote ledger could not be read (path present but "
        "unreadable); failing closed"
    )


def durable_push(
    store: TrumpDeliveryStore,
    message: str,
    *,
    expected: dict,
    block_foreign_claim: bool = False,
) -> str:
    """Commit + push the ledger and VERIFY the record on origin before OK.

    ``expected`` = {post_id, delivery_state, workflow_attempt_id}. Returns
    ``PUSH_OK`` only after re-fetching origin and confirming its ledger has a
    record for this post with OUR ``delivery_state`` and ``workflow_attempt_id``;
    an ``Everything up-to-date`` push without a matching remote record is
    ``PUSH_FAILED``.

    When ``block_foreign_claim`` is set (the initial claim): a remote ``sent``
    returns ``PUSH_CONFLICT_SENT`` and a *foreign* ``claimed``/``ambiguous``
    returns ``PUSH_CONFLICT_CLAIM``, so a re-run never steals a prior attempt's
    post; and if the pre-claim remote cannot be read AND the path is not provably
    absent, the attempt does not add/commit/pull/push on a stale base. Every git
    step is checked; the local commit is reconciled with a freshly-fetched origin
    on EVERY retry so a benign non-fast-forward race can recover; a rebase
    conflict aborts cleanly and fails. Malformed authoritative state fails closed.
    """
    if not durable_enabled():
        return PUSH_DISABLED

    branch = _branch()
    path = _STATE_REL

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
        if block_foreign_claim:
            pre = _git_run("show", f"origin/{branch}:{path}")
            if pre.returncode == 0:
                try:
                    conflict = _remote_conflict_kind(pre.stdout or "", expected)
                except StateReadError:
                    logger.error(
                        "trump CAS pre-read: authoritative remote ledger is "
                        "malformed; failing closed (no claim, no send)"
                    )
                    return PUSH_FAILED
                if conflict is not None:
                    return conflict
            elif not _remote_path_absent(branch):
                # Cannot read the pre-claim remote and the path is not provably
                # absent: do NOT add/commit/pull/push on a stale base.
                continue
        if not _ok("add", path):
            continue
        staged_empty = _git_run("diff", "--cached", "--quiet").returncode == 0
        if not staged_empty:
            if not _ok("commit", "-m", message):
                continue
        # ALWAYS reconcile the (possibly already-committed on a prior retry) local
        # ledger with the freshly-fetched origin before pushing, even when this
        # retry's index is clean. Abort cleanly on conflict.
        if not _ok("pull", "--rebase", "origin", branch):
            _git_run("rebase", "--abort")
            continue
        _git_run("push", "origin", f"HEAD:{branch}")
        # Proof of durability is the REMOTE CONTENT, not the push exit code.
        if not _ok("fetch", "origin", branch):
            continue
        show = _git_run("show", f"origin/{branch}:{path}")
        if show.returncode == 0:
            try:
                verified = _remote_state_has(show.stdout or "", expected)
            except StateReadError:
                verified = False
            if verified:
                return PUSH_OK
    logger.error("trump durable push could not verify the record on origin")
    return PUSH_FAILED
