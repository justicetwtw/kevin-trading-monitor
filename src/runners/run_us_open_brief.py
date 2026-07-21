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
    return {
        "schedule_source": os.getenv("US_OPEN_SCHEDULE_SOURCE", "unknown"),
        "workflow_run_id": os.getenv("GITHUB_RUN_ID", "local"),
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
PUSH_OK = "pushed"  # claim is durable on shared state
PUSH_FAILED = "failed"  # durable mode on but the claim could not be persisted


def _durable_push(message: str) -> str:
    """Commit + push the delivery state to shared state (main) before the send.

    Returns ``PUSH_DISABLED`` when durable mode is off (a no-op used locally / in
    tests, where the trailing ``commit-state`` provides durability), ``PUSH_OK``
    when the claim is durable on shared state, or ``PUSH_FAILED`` when durable
    mode is on but the claim could not be persisted. A ``PUSH_FAILED`` is a hard
    pre-send failure in the caller: the trailing ``commit-state`` cannot
    retroactively satisfy "durable before send".
    """
    if os.getenv("US_OPEN_DURABLE_STATE") != "1":
        return PUSH_DISABLED
    import subprocess
    import time

    branch = os.getenv("US_OPEN_STATE_BRANCH", "main")

    def _git(*args) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, check=False
        )

    _git("config", "user.name", "github-actions[bot]")
    _git(
        "config",
        "user.email",
        "github-actions[bot]@users.noreply.github.com",
    )
    _git("add", str(STATE_PATH))
    if _git("diff", "--staged", "--quiet").returncode == 0:
        # Nothing to commit means the claim is already on shared state (durable).
        return PUSH_OK
    _git("commit", "-m", message)
    for attempt in range(1, 5):
        _git("pull", "--rebase", "origin", branch)
        if _git("push", "origin", f"HEAD:{branch}").returncode == 0:
            return PUSH_OK
        time.sleep(attempt * 2)
    logger.error("us_open durable claim push failed; not sending without a claim")
    return PUSH_FAILED


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
        f"us_open {record['delivery_state']} {session.session_key} [skip ci]"
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

    # Read state once; a corrupt (not merely missing) file fails closed so a
    # lost record can never license a re-send.
    try:
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

    # ACTION_SEND (proceed / retry): generate -> claim durably -> send.
    # Recompute the phase as late as possible before generating, so the body
    # and title reflect the *actual* delivery phase, never the (possibly
    # minutes-old) runner-start phase (generation, claim push and transport all
    # take time, and the step allows several minutes).
    def _sendable(d):
        return (
            d.action == ACTION_SEND
            and d.session is not None
            and d.session.session_key == session.session_key
        )

    def _abort_window_closed(recomputed):
        # The window closed (or the ET session rolled over) while generating /
        # pushing: never fabricate a stale opening brief; record a red miss.
        rec = _fresh(DELIVERY_SKIPPED, status=STATUS_EXPIRED,
                     lateness=recomputed.lateness_minutes)
        rec["stage_code"] = "schedule_delay"
        logger.warning(
            f"us_open {session.session_key} window closed mid-run; not sending"
        )
        return _persist_terminal(store, rec, env, "expired_miss", session,
                                 base_exit=1)

    gen_decision = classify_us_open(_now_taipei())
    if not _sendable(gen_decision):
        return _abort_window_closed(gen_decision)

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

    # Recompute immediately before the send; regenerate the body if the phase
    # crossed a body-type boundary (late -> intraday_recovery) meanwhile.
    send_decision = classify_us_open(_now_taipei())
    if not _sendable(send_decision):
        return _abort_window_closed(send_decision)
    if body_brief_type(send_decision.status) != body_brief_type(
        gen_decision.status
    ):
        body = _generate_body(body_brief_type(send_decision.status))
    record["status"] = send_decision.status
    record["lateness_minutes"] = send_decision.lateness_minutes
    message = render_us_open_message(body, send_decision)

    # Persist the claim locally and durably push it BEFORE the outbound send.
    store.upsert(record)
    if _durable_push(
        f"us_open claim {session.session_key} [skip ci]"
    ) == PUSH_FAILED:
        # Durable mode on but the claim could not be persisted. Sending now would
        # risk a duplicate (a later attempt would see no claim). Fail closed
        # BEFORE Telegram; the trailing commit-state cannot satisfy this after.
        record["delivery_state"] = DELIVERY_FAILED
        record["stage_code"] = "claim_persist_failed"
        _telemetry_only(store, record, "claim_persist_failed",
                        "claim_persist_failed", env,
                        status=send_decision.status,
                        lateness=send_decision.lateness_minutes)
        logger.error(
            f"us_open claim not durably persisted for {session.session_key}; "
            "not sending (retryable in-window)"
        )
        return 1

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
