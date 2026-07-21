"""Dedicated, delay-resilient U.S. opening-brief runner.

Issue #13 / ``docs/market_brief_sla_v1.md``.

This path is isolated from every other brief. Each attempt:

1. recomputes the New York session from the clock (never trusts its cron);
2. reads the session-keyed delivery state for at-most-once semantics;
3. persists a *claim* before the outbound Telegram send;
4. regenerates the brief body at execution time so a late run reflects the
   current market phase, not an open-time snapshot;
5. records ``sent`` / ``failed`` / ``ambiguous`` with public-safe timing fields.

Exit codes: ``0`` when the attempt did the right thing (sent, or correctly
skipped a duplicate / early / expired / wrong-session attempt), ``1`` when a
required send failed or delivery is ambiguous — so the workflow never finishes
green while an opening brief is genuinely unsent or in doubt.
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
    classify_us_open,
    render_us_open_message,
)
from src.runners.us_open_state import (
    DELIVERY_AMBIGUOUS,
    DELIVERY_FAILED,
    DELIVERY_SENT,
    DELIVERY_SKIPPED,
    DO_AMBIGUOUS,
    DO_SKIP_AMBIGUOUS,
    DO_SKIP_DUPLICATE,
    LEGACY_DEDUP_PATH,
    STATE_PATH,
    UsOpenDeliveryStore,
    new_record,
    resolve_delivery_action,
)


def _now_taipei() -> datetime:
    """Wall clock as Asia/Taipei. Patched in tests to freeze the attempt time."""
    return datetime.now(TIMEZONE_USER)


def _build_store() -> UsOpenDeliveryStore:
    return UsOpenDeliveryStore(STATE_PATH, legacy_path=LEGACY_DEDUP_PATH)


def _generate_body() -> str:
    """Regenerate the current us_open brief body at execution time.

    Imported lazily so the heavy data stack only loads when an attempt actually
    sends (early / duplicate / expired attempts stay cheap).
    """
    from src.alerts.brief_generator import BriefGenerator

    return BriefGenerator("us_open").generate()


def _send(message: str) -> bool:
    from src.alerts.telegram_bot import send_telegram

    # The opening brief is a foreground notification (never silent).
    return send_telegram(message, parse_mode="HTML", disable_notification=False)


def main() -> int:
    now = _now_taipei()
    schedule_source = os.getenv("US_OPEN_SCHEDULE_SOURCE", "unknown")
    workflow_run_id = os.getenv("GITHUB_RUN_ID", "local")

    decision = classify_us_open(now)
    store = _build_store()
    store.migrate_legacy()

    # Attempts with no valid session key: nothing to record, just skip.
    if decision.action == ACTION_SKIP_WRONG_SESSION:
        logger.info(f"us_open skip: {decision.reason}")
        return 0
    if decision.action == ACTION_SKIP_EARLY:
        logger.info(f"us_open skip (early): {decision.reason}")
        return 0

    session = decision.session
    existing = store.get(session.session_key)
    delivery_action = resolve_delivery_action(existing)

    # Idempotency / ambiguity checks come before any expired/send handling so a
    # session that was already delivered is never re-touched.
    if delivery_action == DO_SKIP_DUPLICATE:
        logger.info(
            f"us_open already delivered for {session.session_key}; skip duplicate"
        )
        return 0
    if delivery_action == DO_SKIP_AMBIGUOUS:
        logger.warning(
            f"us_open {session.session_key} previously flagged ambiguous; "
            "leaving for manual review, not resending"
        )
        return 0
    if delivery_action == DO_AMBIGUOUS:
        record = dict(existing)
        record["delivery_state"] = DELIVERY_AMBIGUOUS
        record["stage_code"] = "ambiguous_delivery"
        store.upsert(record)
        logger.error(
            f"us_open {session.session_key}: prior claim never resolved to "
            "sent/failed; marking ambiguous_delivery and not auto-duplicating"
        )
        return 1

    # Session closed and never delivered: do not fabricate an opening brief.
    if decision.action == ACTION_SKIP_EXPIRED:
        record = new_record(
            session,
            status=STATUS_EXPIRED,
            lateness_minutes=decision.lateness_minutes,
            schedule_source=schedule_source,
            workflow_run_id=workflow_run_id,
            workflow_started_at=now.isoformat(),
            delivery_state=DELIVERY_SKIPPED,
        )
        record["stage_code"] = "schedule_delay"
        store.upsert(record)
        logger.warning(
            f"us_open {session.session_key} expired "
            f"(+{decision.lateness_minutes}m, session closed); recorded miss, "
            "not sending a stale opening brief"
        )
        return 0

    # ACTION_SEND with delivery_action in {proceed, retry}: claim -> send.
    if decision.action != ACTION_SEND:  # defensive; unreachable
        logger.error(f"us_open unexpected action {decision.action}")
        return 1

    record = new_record(
        session,
        status=decision.status,
        lateness_minutes=decision.lateness_minutes,
        schedule_source=schedule_source,
        workflow_run_id=workflow_run_id,
        workflow_started_at=now.isoformat(),
    )
    record["generation_started_at"] = _now_taipei().isoformat()
    try:
        body = _generate_body()
    except Exception as exc:  # noqa: BLE001 - generation must fail closed
        # No claim was persisted yet, so a generation failure stays cleanly
        # retryable: the next attempt sees 'failed' and retries in-window.
        record["delivery_state"] = DELIVERY_FAILED
        record["stage_code"] = "generation_failed"
        store.upsert(record)
        logger.error(f"us_open generation failed: {type(exc).__name__}")
        return 1

    record["generation_finished_at"] = _now_taipei().isoformat()
    message = render_us_open_message(body, decision)

    # Persist the claim immediately BEFORE the outbound send, so the only
    # unresolved-'claimed' window is a crash during the send itself — the
    # genuine exactly-once ambiguity, surfaced (not auto-duplicated) next run.
    store.upsert(record)

    if not _send(message):
        record["delivery_state"] = DELIVERY_FAILED
        record["stage_code"] = "telegram_send_failed"
        store.upsert(record)
        logger.error(
            f"us_open send failed for {session.session_key} "
            f"(status={decision.status}); state=failed, retryable in-window"
        )
        return 1

    record["delivery_state"] = DELIVERY_SENT
    record["sent_at"] = _now_taipei().isoformat()
    record["stage_code"] = None
    store.upsert(record)
    logger.info(
        f"us_open delivered {session.session_key} status={decision.status} "
        f"lateness={decision.lateness_minutes}m"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
