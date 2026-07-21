"""Dedicated, delay-resilient U.S. opening-brief runner.

Issue #13 / ``docs/market_brief_sla_v1.md``.

This path is isolated from every other brief. Each attempt:

1. recomputes the New York session from the clock (never trusts its cron);
2. reads the session-keyed delivery state, failing closed if it is corrupt;
3. persists a *claim* and durably pushes it to shared state before the send, so
   a crash after send surfaces ``ambiguous_delivery`` instead of re-sending;
4. regenerates the brief body at execution time with a phase-appropriate
   template so a late/intraday run never presents an open-time snapshot;
5. records ``sent`` / ``failed`` / ``ambiguous`` with public-safe timing fields,
   distinguishing a definitive send failure (retryable) from an ambiguous
   outcome (surface, never auto-retry).

Exit codes: ``0`` only when the attempt did the right thing (sent, or correctly
skipped a duplicate / early / wrong-session attempt). ``1`` when a required
opening brief is unsent, missed (expired) or in doubt (ambiguous) — so the
workflow never finishes green while delivery is unproven (contract section 6).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

from loguru import logger

from src.config.settings import TIMEZONE_USER
from src.runners.us_open_sla import (
    ACTION_SEND,
    ACTION_SKIP_EARLY,
    ACTION_SKIP_EXPIRED,
    ACTION_SKIP_WRONG_SESSION,
    STATUS_EXPIRED,
    body_brief_type,
    classify_us_open,
    render_us_open_message,
)
from src.runners.us_open_state import (
    DELIVERY_AMBIGUOUS,
    DELIVERY_FAILED,
    DELIVERY_OBSERVING,
    DELIVERY_SENT,
    DELIVERY_SKIPPED,
    DO_AMBIGUOUS,
    DO_SKIP_AMBIGUOUS,
    DO_SKIP_DUPLICATE,
    LEGACY_DEDUP_PATH,
    STATE_PATH,
    StateReadError,
    UsOpenDeliveryStore,
    new_record,
    record_attempt,
    resolve_delivery_action,
)


def _now_taipei() -> datetime:
    """Wall clock as Asia/Taipei. Patched in tests to freeze the attempt time."""
    return datetime.now(TIMEZONE_USER)


def _env() -> dict:
    run_id = os.getenv("GITHUB_RUN_ID", "local")
    # A GitHub re-run keeps the same run id and (re-runs of a scheduled workflow)
    # the same checked-out SHA, but increments run_attempt. Identify a delivery
    # attempt by run id + attempt so a re-run cannot claim a prior attempt's
    # remote record as its own.
    run_attempt = os.getenv("GITHUB_RUN_ATTEMPT", "1")
    return {
        "schedule_source": os.getenv("US_OPEN_SCHEDULE_SOURCE", "unknown"),
        "workflow_run_id": run_id,
        "workflow_attempt_id": f"{run_id}:{run_attempt}",
        # Real workflow first-step time, captured before Python setup/install so
        # GitHub queue delay is separable from runner/setup delay (contract §6).
        "workflow_started_at": os.getenv("US_OPEN_WORKFLOW_STARTED_AT") or None,
    }


def _build_store() -> UsOpenDeliveryStore:
    return UsOpenDeliveryStore(STATE_PATH, legacy_path=LEGACY_DEDUP_PATH)


def _generate_body(brief_type: str) -> str:
    """Regenerate the current brief body at execution time.

    Imported lazily so the heavy data stack only loads when an attempt actually
    sends (early / duplicate / expired attempts stay cheap).
    """
    from src.alerts.brief_generator import BriefGenerator

    return BriefGenerator(brief_type).generate()


def _send_detailed(message: str) -> dict:
    """Tri-state Telegram send: {'outcome': 'sent'|'failed'|'ambiguous', ...}.

    ``sensitive=True`` keeps the brief body (which may include portfolio health
    and translated content) out of the public Actions logs.
    """
    from src.alerts.telegram_bot import send_telegram_detailed

    # The opening brief is a foreground notification (never silent).
    return send_telegram_detailed(
        message, parse_mode="HTML", disable_notification=False, sensitive=True
    )


# Durable-push outcomes.
PUSH_DISABLED = "disabled"  # durable mode off (local/tests): rely on commit-state
PUSH_OK = "pushed"  # claim is durable and verified on shared state
PUSH_FAILED = "failed"  # durable mode on but the claim could not be verified
PUSH_CONFLICT_SENT = "conflict_sent"  # another attempt already DELIVERED this session
PUSH_CONFLICT_CLAIM = "conflict_claim"  # another attempt holds an unresolved claim

# Bounded phase-stabilization rounds after a verified claim (fail red, not spin).
_MAX_STABILIZE_ROUNDS = 3


def _git_run(*args):
    """Run one git subprocess (CI-only; patched in tests)."""
    import subprocess

    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=False
    )


def _sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)


def _remote_record(content: str, session_key: str) -> dict | None:
    """Look up a session record in remote state via the SHARED fail-closed
    validator (``UsOpenDeliveryStore.parse_state``), so hydration, the claim
    compare-and-swap and post-push verification all interpret origin identically.

    Raises ``StateReadError`` when the remote payload is malformed/unreadable
    (unparsable JSON, non-object root, unsupported schema, missing/invalid
    ``sessions`` map, or a malformed individual record) — callers map that to a
    controlled red/no-send rather than letting it throw through to the trailing
    generic state writer. Returns ``None`` only when the state is valid but has no
    record for this session.
    """
    sessions = UsOpenDeliveryStore.parse_state(
        content, origin="origin/main state"
    )["sessions"]
    record = sessions.get(session_key)
    return record if isinstance(record, dict) else None


def _remote_state_has(content: str, expected: dict) -> bool:
    """True iff origin has the expected session record with OUR attempt identity.

    Identity is matched on ``workflow_attempt_id`` (run id + run attempt), not the
    reused ``workflow_run_id``, so a re-run cannot verify a prior attempt's record.
    Raises ``StateReadError`` if the remote payload is malformed (the caller treats
    an unverifiable remote as not-yet-durable). Note this proves the session's
    delivery_state + attempt identity, not full claim metadata such as
    status/lateness.
    """
    record = _remote_record(content, expected["session_key"])
    if record is None:
        return False
    return (
        record.get("delivery_state") == expected["delivery_state"]
        and record.get("workflow_attempt_id") == expected.get("workflow_attempt_id")
    )


def _remote_conflict_kind(content: str, expected: dict) -> str | None:
    """Classify a compare-and-swap conflict against origin's validated state.

    Returns ``PUSH_CONFLICT_SENT`` if origin already shows this session delivered
    (by any attempt), ``PUSH_CONFLICT_CLAIM`` if a *different* attempt holds an
    unresolved ``claimed``/``ambiguous`` record, else ``None`` (no conflict — a
    missing record or this attempt's own claim). Raises ``StateReadError`` on a
    malformed remote payload (the caller fails closed rather than sending on top
    of an unreadable authoritative record).
    """
    record = _remote_record(content, expected["session_key"])
    if record is None:
        return None
    state = record.get("delivery_state")
    if state == "sent":
        return PUSH_CONFLICT_SENT
    if state in ("claimed", "ambiguous"):
        if record.get("workflow_attempt_id") != expected.get("workflow_attempt_id"):
            return PUSH_CONFLICT_CLAIM
    return None


def _remote_path_absent(branch: str) -> bool:
    """True only if the state file is PROVABLY absent from ``origin/<branch>``.

    ``git ls-tree`` exits 0 with empty output only when the path does not exist in
    the tree; any non-zero result, or a listed entry, is NOT proof of absence.
    This lets a genuine first-ever run bootstrap while a transient/unreadable
    object (which must fail closed) is never mistaken for "no state yet".
    """
    result = _git_run("ls-tree", f"origin/{branch}", "--", str(STATE_PATH))
    return result.returncode == 0 and not (result.stdout or "").strip()


def _durable_push(message: str, *, expected: dict, block_foreign_claim: bool = False) -> str:
    """Commit + push the delivery state and VERIFY it on origin before OK.

    ``expected`` = {session_key, delivery_state, workflow_attempt_id}. Returns
    ``PUSH_OK`` only after re-fetching origin and confirming its state file has a
    record for this session with OUR ``delivery_state`` and ``workflow_attempt_id``
    (identity + state, not full claim metadata); an ``Everything up-to-date`` push
    without a matching remote record is ``PUSH_FAILED``.

    Every remote payload is read through the shared fail-closed validator, so a
    malformed authoritative state maps to ``PUSH_FAILED`` (red/no-send), never an
    uncaught exception. When ``block_foreign_claim`` is set (the initial claim): a
    remote ``sent`` returns ``PUSH_CONFLICT_SENT`` and a *foreign*
    ``claimed``/``ambiguous`` returns ``PUSH_CONFLICT_CLAIM`` so a re-run never
    steals a prior attempt's session; and if the pre-claim remote state cannot be
    read AND the path is not provably absent, the attempt does not proceed to
    add/commit/pull/push on a stale base. Every git step is checked; the local
    commit is reconciled with a freshly-fetched origin on EVERY retry (even when
    the index is clean) so a benign non-fast-forward race can recover; a
    ``pull --rebase`` conflict aborts cleanly and fails.
    """
    if os.getenv("US_OPEN_DURABLE_STATE") != "1":
        return PUSH_DISABLED

    branch = os.getenv("US_OPEN_STATE_BRANCH", "main")

    def _ok(*args) -> bool:
        return _git_run(*args).returncode == 0

    _git_run("config", "user.name", "github-actions[bot]")
    _git_run(
        "config", "user.email", "github-actions[bot]@users.noreply.github.com"
    )

    for attempt in range(1, 5):
        if attempt > 1:
            _sleep((attempt - 1) * 2)
        # Refresh the base so we reconcile onto the latest shared state.
        if not _ok("fetch", "origin", branch):
            continue
        # Compare-and-swap gate for the initial claim: never overwrite another
        # attempt's delivery/unresolved claim, and never claim on top of an
        # unreadable authoritative state.
        if block_foreign_claim:
            pre = _git_run("show", f"origin/{branch}:{STATE_PATH}")
            if pre.returncode == 0:
                try:
                    conflict = _remote_conflict_kind(pre.stdout or "", expected)
                except StateReadError:
                    logger.error(
                        "us_open CAS pre-read: authoritative remote state is "
                        "malformed; failing closed (no claim, no send)"
                    )
                    return PUSH_FAILED
                if conflict is not None:
                    return conflict
            elif not _remote_path_absent(branch):
                # Cannot read the pre-claim remote state and the path is not
                # provably absent: do NOT add/commit/pull/push on a stale base.
                continue
        # A failed `add` must not be read as "nothing to commit".
        if not _ok("add", str(STATE_PATH)):
            continue
        staged_empty = _git_run("diff", "--cached", "--quiet").returncode == 0
        if not staged_empty:
            # A real commit must succeed before any push can be durable.
            if not _ok("commit", "-m", message):
                continue
        # ALWAYS reconcile the (possibly already-committed on a prior retry) local
        # state with the freshly-fetched origin before pushing, even when this
        # retry's index is clean — otherwise a benign non-fast-forward race would
        # keep re-pushing the same stale commit. Abort cleanly on conflict.
        if not _ok("pull", "--rebase", "origin", branch):
            _git_run("rebase", "--abort")
            continue
        _git_run("push", "origin", f"HEAD:{branch}")
        # Proof of durability is the REMOTE CONTENT, not the push exit code:
        # re-fetch and confirm origin's state file has our exact record. A
        # malformed remote here cannot prove durability (retry / fail closed).
        if not _ok("fetch", "origin", branch):
            continue
        show = _git_run("show", f"origin/{branch}:{STATE_PATH}")
        if show.returncode == 0:
            try:
                verified = _remote_state_has(show.stdout or "", expected)
            except StateReadError:
                verified = False
            if verified:
                return PUSH_OK
    logger.error("us_open durable push could not verify state on origin")
    return PUSH_FAILED


def _hydrate_local_from_remote(store) -> bool:
    """Replace the local state with origin's authoritative version before any
    delivery decision (durable mode only; no-op locally/in tests).

    A scheduled run or GitHub re-run may check out the original event SHA even
    after a previous watchdog has pushed a newer claim/sent record; a stale local
    file must never license a new claim. Fetches origin, reads
    ``origin/<branch>:data_store/us_open_delivery_state.json`` and validates it
    with the same fail-closed rules.

    Fails closed (``StateReadError``, mapped to red/no-send by the caller) if
    origin cannot be fetched, if the remote object cannot be read while the path
    is not PROVABLY absent (a transient/unreadable object must never be mistaken
    for "first run ever" — this PR ships the state file, so after rollout a
    missing object is not a safe empty-state signal), or if the remote state is
    malformed. Only an explicitly verified absent path bootstraps a genuine first
    run.
    """
    if os.getenv("US_OPEN_DURABLE_STATE") != "1":
        return False
    branch = os.getenv("US_OPEN_STATE_BRANCH", "main")
    if _git_run("fetch", "origin", branch).returncode != 0:
        raise StateReadError("cannot fetch origin to hydrate authoritative state")
    show = _git_run("show", f"origin/{branch}:{STATE_PATH}")
    if show.returncode == 0:
        store.hydrate_from(show.stdout or "")
        return True
    # `git show` failed: only a provably-absent path is a legitimate first run.
    # Any other read failure fails closed so a stale checkout cannot become
    # authoritative and license a duplicate send.
    if _remote_path_absent(branch):
        return True
    raise StateReadError(
        "authoritative remote state could not be read (path present but "
        "unreadable); failing closed"
    )


def _telemetry_only(store, record, outcome, stage_code, env, *,
                    status=None, lateness=None) -> None:
    """Append an attributable attempt entry and persist, without (re)sending."""
    record_attempt(
        record, outcome, stage_code,
        at=_now_taipei().isoformat(),
        workflow_run_id=env["workflow_run_id"],
        schedule_source=env["schedule_source"],
        workflow_started_at=env.get("workflow_started_at"),
        status=status,
        lateness_minutes=lateness,
    )
    store.upsert(record)


def _persist_terminal(store, record, env, outcome_label, session, *, base_exit):
    """Record a terminal outcome locally AND durably persist it before return.

    Contract §4 requires the Telegram result to be persisted immediately. If the
    post-send durable push fails, the durable claim stays on shared state; we
    surface red with a generic ``state_persist_failed`` rather than let a
    delivered brief later read as a false ambiguous, or a failure lose its
    safe-retry state, on the next watchdog.
    """
    _telemetry_only(store, record, outcome_label, record.get("stage_code"), env,
                    status=record.get("status"),
                    lateness=record.get("lateness_minutes"))
    push = _durable_push(
        f"us_open {record['delivery_state']} {session.session_key} [skip ci]",
        expected={
            "session_key": session.session_key,
            "delivery_state": record["delivery_state"],
            "workflow_attempt_id": env["workflow_attempt_id"],
        },
    )
    if push == PUSH_FAILED:
        _telemetry_only(store, record, "state_persist_failed",
                        "state_persist_failed", env)
        logger.error(
            f"us_open terminal state not durably persisted for "
            f"{session.session_key}; workflow red"
        )
        return 1
    return base_exit


def main() -> int:
    runner_started = _now_taipei()
    env = _env()
    workflow_started_at = env["workflow_started_at"] or runner_started.isoformat()
    decision = classify_us_open(runner_started)
    store = _build_store()

    # Weekend / non-trading day: no session key, nothing durable to record.
    if decision.action == ACTION_SKIP_WRONG_SESSION:
        logger.info(f"us_open skip: {decision.reason}")
        return 0

    session = decision.session

    # Hydrate origin's authoritative state, then read it. A corrupt (not merely
    # missing) file — local or remote — fails closed so a lost/stale record can
    # never license a re-send, and a stale checkout can never out-vote a newer
    # remote claim/sent.
    try:
        _hydrate_local_from_remote(store)
        store.migrate_legacy(max_session_date_et=session.session_date_et)
        existing = store.get(session.session_key)
    except StateReadError as exc:
        logger.error(
            f"us_open FAIL CLOSED: delivery state unreadable ({exc}); "
            "not sending, not rewriting state"
        )
        return 1

    delivery_action = resolve_delivery_action(existing)

    lateness = decision.lateness_minutes

    def _fresh(delivery_state, status=None, lateness=None):
        record = new_record(
            session,
            status=status,
            lateness_minutes=lateness,
            schedule_source=env["schedule_source"],
            workflow_run_id=env["workflow_run_id"],
            workflow_attempt_id=env["workflow_attempt_id"],
            workflow_started_at=workflow_started_at,
            runner_started_at=runner_started.isoformat(),
            delivery_state=delivery_state,
        )
        # Carry the bounded attempt history forward across every state
        # transition so an early wrong-DST attempt or a prior failed attempt
        # remains visible after a later attempt sends.
        if existing and isinstance(existing.get("observed_attempts"), list):
            record["observed_attempts"] = list(existing["observed_attempts"])
        return record

    # Before the open: durable "observing" telemetry, then wait for a later
    # attempt. Never overwrite a claim/sent/failed/ambiguous record.
    if decision.action == ACTION_SKIP_EARLY:
        if existing is None or existing.get("delivery_state") in (
            None,
            DELIVERY_OBSERVING,
            DELIVERY_SKIPPED,
        ):
            record = dict(existing) if existing else _fresh(DELIVERY_OBSERVING)
            record["delivery_state"] = DELIVERY_OBSERVING
            _telemetry_only(store, record, "early", None, env)
        logger.info(f"us_open early: {decision.reason}")
        return 0

    # Already delivered this session: durable telemetry, no resend (green).
    if delivery_action == DO_SKIP_DUPLICATE:
        _telemetry_only(store, dict(existing), "duplicate", None, env)
        logger.info(
            f"us_open already delivered {session.session_key}; skip duplicate"
        )
        return 0

    # Previously surfaced as ambiguous: stay red until manually cleared
    # (contract section 6 — not green while delivery is in doubt).
    if delivery_action == DO_SKIP_AMBIGUOUS:
        _telemetry_only(
            store, dict(existing), "ambiguous_repeat", "ambiguous_delivery", env
        )
        logger.warning(
            f"us_open {session.session_key} still ambiguous; not resending, "
            "workflow stays red until the record is cleared"
        )
        return 1

    # A prior claim never resolved to sent/failed (crash mid-send): surface,
    # never auto-duplicate.
    if delivery_action == DO_AMBIGUOUS:
        record = dict(existing)
        record["delivery_state"] = DELIVERY_AMBIGUOUS
        record["stage_code"] = "ambiguous_delivery"
        _telemetry_only(
            store, record, "ambiguous_from_claim", "ambiguous_delivery", env
        )
        logger.error(
            f"us_open {session.session_key}: prior claim unresolved; "
            "marking ambiguous_delivery and not auto-duplicating"
        )
        return 1

    # Session closed and never delivered: never fabricate an opening brief. A
    # completely missed required send is RED (contract section 6); a prior
    # send failure is preserved rather than overwritten as a benign skip.
    if decision.action == ACTION_SKIP_EXPIRED:
        if existing and existing.get("delivery_state") == DELIVERY_FAILED:
            record = dict(existing)
            record["status"] = STATUS_EXPIRED
            _telemetry_only(
                store, record, "expired_after_failure",
                record.get("stage_code") or "telegram_send_failed", env,
                status=STATUS_EXPIRED, lateness=lateness,
            )
        else:
            record = _fresh(
                DELIVERY_SKIPPED, status=STATUS_EXPIRED, lateness=lateness
            )
            record["stage_code"] = "schedule_delay"
            _telemetry_only(
                store, record, "expired_miss", "schedule_delay", env,
                status=STATUS_EXPIRED, lateness=lateness,
            )
        logger.warning(
            f"us_open {session.session_key} expired "
            f"(+{lateness}m, session closed); recorded miss"
        )
        return 1

    if decision.action != ACTION_SEND:  # defensive; unreachable
        logger.error(f"us_open unexpected action {decision.action}")
        return 1

    # ACTION_SEND (proceed / retry): generate -> claim durably (remote-verified)
    # -> stabilize phase -> send.
    def _sendable(d):
        return (
            d.action == ACTION_SEND
            and d.session is not None
            and d.session.session_key == session.session_key
        )

    def _expected(state):
        # Identity the remote state must contain for a push to count as durable —
        # the UNIQUE attempt id, so a re-run cannot verify a prior attempt's record.
        return {
            "session_key": session.session_key,
            "delivery_state": state,
            "workflow_attempt_id": env["workflow_attempt_id"],
        }

    def _foreign_conflict(kind):
        # A concurrent attempt landed a delivery/claim on origin between our
        # authoritative hydration and our claim push (e.g. a GitHub re-run of a
        # crashed attempt). Discard our dirty local claim and restore origin's
        # authoritative snapshot so the always-run trailing commit-state pushes NO
        # replacement session record, then classify:
        #   remote sent      -> clean duplicate (green), remote record preserved;
        #   remote claimed/   -> red / no-send, foreign record and its owner
        #   ambiguous            (workflow_attempt_id) preserved exactly.
        # We deliberately make no current-attempt session mutation here: the
        # foreign attempt keeps ownership, and a later watchdog resolves any
        # still-unresolved claim via the hydration path.
        try:
            _hydrate_local_from_remote(store)
        except StateReadError as exc:
            logger.error(
                f"us_open {session.session_key}: conflict resync failed "
                f"({exc}); not sending, workflow red"
            )
            return 1
        if kind == PUSH_CONFLICT_SENT:
            logger.info(
                f"us_open {session.session_key}: another attempt already "
                "delivered; duplicate skip (green), remote record preserved"
            )
            return 0
        logger.error(
            f"us_open {session.session_key}: another attempt owns the claim; "
            "not sending, remote record preserved, workflow red"
        )
        return 1

    def _claim_persist_failed(dec):
        # Sending without a remotely-durable claim risks a duplicate; fail closed
        # before Telegram. The trailing commit-state cannot satisfy this after.
        record["delivery_state"] = DELIVERY_FAILED
        record["stage_code"] = "claim_persist_failed"
        _telemetry_only(store, record, "claim_persist_failed",
                        "claim_persist_failed", env,
                        status=dec.status, lateness=dec.lateness_minutes)
        logger.error(
            f"us_open claim not durably persisted for {session.session_key}; "
            "not sending (retryable in-window)"
        )
        return 1

    def _closed_mid_run(reason):
        record["delivery_state"] = DELIVERY_SKIPPED
        record["status"] = STATUS_EXPIRED
        record["stage_code"] = "schedule_delay"
        logger.warning(f"us_open {session.session_key} {reason}; not sending")
        return _persist_terminal(store, record, env, "expired_miss", session,
                                 base_exit=1)

    gen_decision = classify_us_open(_now_taipei())
    if not _sendable(gen_decision):
        return _closed_mid_run("window closed before generation")

    record = _fresh("claimed", status=gen_decision.status,
                    lateness=gen_decision.lateness_minutes)
    record["generation_started_at"] = _now_taipei().isoformat()
    try:
        body = _generate_body(body_brief_type(gen_decision.status))
    except Exception as exc:  # noqa: BLE001 - generation must fail closed
        record["delivery_state"] = DELIVERY_FAILED
        record["stage_code"] = "generation_failed"
        return _persist_terminal(store, record, env, "generation_failed",
                                 session, base_exit=1)
    record["generation_finished_at"] = _now_taipei().isoformat()
    current_body_type = body_brief_type(gen_decision.status)

    # Persist the claim (the delivery lock) locally and durably push it,
    # verifying the record is actually on origin, BEFORE the outbound send. The
    # first claim is compare-and-swap gated: it will not steal another attempt's
    # unresolved claim or a prior delivery (the GitHub re-run path).
    message = render_us_open_message(body, gen_decision)
    store.upsert(record)
    claim_push = _durable_push(
        f"us_open claim {session.session_key} [skip ci]",
        expected=_expected("claimed"),
        block_foreign_claim=True,
    )
    if claim_push in (PUSH_CONFLICT_SENT, PUSH_CONFLICT_CLAIM):
        return _foreign_conflict(claim_push)
    if claim_push == PUSH_FAILED:
        return _claim_persist_failed(gen_decision)

    # The claim push can take seconds; the phase may have advanced. Stabilize:
    # recompute -> regenerate body when the type changed -> re-verify the claim,
    # until status/body-type are stable immediately before the request. Bounded
    # so a persistently-drifting clock fails red rather than spins.
    send_decision = gen_decision
    stabilized = False
    for _ in range(_MAX_STABILIZE_ROUNDS):
        deliver_decision = classify_us_open(_now_taipei())
        if not _sendable(deliver_decision):
            return _closed_mid_run("window closed during claim push")
        if (
            deliver_decision.status == record["status"]
            and body_brief_type(deliver_decision.status) == current_body_type
        ):
            # Stable SLA class, but the clock still advanced: copy the
            # request-time status/lateness so a failed/ambiguous outcome never
            # retains stale generation-time lateness.
            record["status"] = deliver_decision.status
            record["lateness_minutes"] = deliver_decision.lateness_minutes
            message = render_us_open_message(body, deliver_decision)
            send_decision = deliver_decision
            stabilized = True
            break
        if body_brief_type(deliver_decision.status) != current_body_type:
            try:
                body = _generate_body(body_brief_type(deliver_decision.status))
            except Exception as exc:  # noqa: BLE001 - fail closed, like initial gen
                # The claim is durable; a regeneration crash must NOT leave it
                # 'claimed' (a false permanent ambiguity). Persist a retryable
                # failed terminal instead, and never call Telegram.
                record["delivery_state"] = DELIVERY_FAILED
                record["stage_code"] = "generation_failed"
                logger.error(
                    f"us_open stabilization regeneration failed for "
                    f"{session.session_key}: {type(exc).__name__}"
                )
                return _persist_terminal(store, record, env, "generation_failed",
                                         session, base_exit=1)
            current_body_type = body_brief_type(deliver_decision.status)
        record["status"] = deliver_decision.status
        record["lateness_minutes"] = deliver_decision.lateness_minutes
        message = render_us_open_message(body, deliver_decision)
        store.upsert(record)
        if _durable_push(
            f"us_open claim {session.session_key} [skip ci]",
            expected=_expected("claimed"),
        ) == PUSH_FAILED:
            return _claim_persist_failed(deliver_decision)
        send_decision = deliver_decision

    if not stabilized:
        record["delivery_state"] = DELIVERY_FAILED
        record["stage_code"] = "phase_unstable"
        logger.error(
            f"us_open phase did not stabilize for {session.session_key}; "
            "not sending"
        )
        return _persist_terminal(store, record, env, "phase_unstable", session,
                                 base_exit=1)

    # Persist the exact request-time SLA class/lateness before the send, so a
    # failed/ambiguous outcome reflects the request moment, not generation time.
    record["status"] = send_decision.status
    record["lateness_minutes"] = send_decision.lateness_minutes
    outcome = _send_detailed(message)
    result = outcome.get("outcome")

    if result == "sent":
        sent_at = _now_taipei()
        record["delivery_state"] = DELIVERY_SENT
        record["sent_at"] = sent_at.isoformat()
        record["stage_code"] = None
        # Final status/lateness from the actual delivery timestamp.
        final = classify_us_open(sent_at)
        if (
            final.session is not None
            and final.session.session_key == session.session_key
            and final.lateness_minutes is not None
        ):
            record["lateness_minutes"] = final.lateness_minutes
            if final.action == ACTION_SEND:
                record["status"] = final.status
        logger.info(
            f"us_open delivered {session.session_key} "
            f"status={record['status']} lateness={record['lateness_minutes']}m"
        )
        return _persist_terminal(store, record, env, "sent", session,
                                 base_exit=0)

    if result == "ambiguous":
        # Timeout / partial / server-side: the message may have gone out. Do NOT
        # auto-retry; surface ambiguity so it is not silently duplicated.
        record["delivery_state"] = DELIVERY_AMBIGUOUS
        record["stage_code"] = "ambiguous_delivery"
        logger.error(
            f"us_open send ambiguous for {session.session_key} "
            f"(delivered {outcome.get('delivered')}/{outcome.get('total')}); "
            "not auto-retrying"
        )
        return _persist_terminal(store, record, env, "send_ambiguous", session,
                                 base_exit=1)

    # Definitive rejection: certainly not delivered; retryable in-window.
    record["delivery_state"] = DELIVERY_FAILED
    record["stage_code"] = "telegram_send_failed"
    logger.error(
        f"us_open send failed for {session.session_key} "
        f"(status={send_decision.status}); state=failed, retryable in-window"
    )
    return _persist_terminal(store, record, env, "send_failed", session,
                             base_exit=1)


if __name__ == "__main__":
    sys.exit(main())
