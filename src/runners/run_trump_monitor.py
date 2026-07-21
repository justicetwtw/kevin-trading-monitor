"""Capture and deliver every new Donald Trump Truth Social activity.

Keywords never decide whether an activity is retained or delivered. Tier only
controls notification urgency. The monitor uses a 24-hour first-run checkpoint,
keeps source health explicit, and marks a split post seen only after its final
fragment reaches every configured Telegram recipient.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from dateutil.parser import isoparse
from loguru import logger

from src.alerts.telegram_bot import send_telegram, send_telegram_detailed
from src.alerts.translation import (
    TranslationResult,
    get_default_translator,
    is_noop_text,
    reset_translation_cache,
    translate_text,
)
from src.config import trump_translation_config as translation_config
from src.config.market_clock import TAIPEI
from src.data.trump_truth import (
    ArchiveError,
    archive_posts,
    fetch_recent_posts_with_health,
    get_archived_posts,
)
from src.storage.state_manager import read_json, write_json
from src.storage.trump_delivery_remote import (
    PUSH_CONFLICT_CLAIM,
    PUSH_CONFLICT_SENT,
    PUSH_FAILED,
    durable_push,
    durable_push_capture,
    hydrate_archive_from_remote,
    hydrate_from_remote,
    hydrate_legacy_from_remote,
)
from src.storage.trump_delivery_state import (
    DELIVERY_AMBIGUOUS,
    DELIVERY_CLAIMED,
    DELIVERY_FAILED,
    DELIVERY_PENDING,
    DO_PROCEED,
    DO_RETRY,
    StateReadError,
    TrumpDeliveryStore,
    resolve_delivery_action,
)

# Bounded retry-from-archive work per run: a large failed backlog is retried a
# chunk at a time (oldest first) so no single run is unbounded.
MAX_ARCHIVE_RETRY_PER_RUN = 50

HEALTH_FILE = "trump_monitor_health.json"
MAX_TELEGRAM_CHARS = 3600
UNAVAILABLE_NOTICE_COOLDOWN = timedelta(hours=6)
INITIAL_BACKFILL_WINDOW = timedelta(hours=24)

# Monotonic clock indirection so the run-level translation budget is
# deterministic and injectable in tests (no wall-clock sleeps).
_monotonic = time.monotonic


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = isoparse(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _capture_started_at(store: TrumpDeliveryStore) -> datetime:
    """Resolve the capture checkpoint from the fail-closed delivery ledger.

    The checkpoint lives in the atomic, fail-closed ledger, which is hydrated
    from authoritative ``origin/main`` before this is read — so it is never taken
    from a possibly-stale event checkout. On a genuine first run (no checkpoint
    in the ledger) it defaults to the 24h backfill window; a stale checkout's
    health checkpoint is deliberately NOT adopted, because dedup is guaranteed by
    the authoritative ledger + origin-hydrated legacy seen, so a 24h window can
    never re-blast an already-delivered post.
    """
    existing = _parse_time(store.capture_started_at())
    if existing is not None:
        return existing
    started = datetime.now(timezone.utc) - INITIAL_BACKFILL_WINDOW
    store.set_capture_started_at(started.isoformat())
    return started


def _eligible_since_checkpoint(
    posts: list[dict[str, Any]],
    capture_started_at: datetime,
) -> tuple[list[dict[str, Any]], int]:
    """Exclude historical archive rows and count timestamp-invalid activities."""
    eligible: list[dict[str, Any]] = []
    missing_timestamp = 0
    for post in posts:
        created = _parse_time(post.get("created_at"))
        if created is None:
            missing_timestamp += 1
        elif created >= capture_started_at:
            eligible.append(post)
    return eligible, missing_timestamp


def _taipei_time(value: Any) -> str:
    parsed = _parse_time(value)
    if parsed is None:
        return "時間未知"
    return parsed.astimezone(TAIPEI).strftime("%Y-%m-%d %H:%M 台北")


def _translated_body(english: str, translation: TranslationResult) -> str:
    """Render the Chinese-first, full-English body for one post.

    Translation failure never drops the English original: it falls back to an
    explicit notice plus the complete English text.
    """
    if translation.status == "ok" and (translation.text or "").strip():
        return (
            "【繁體中文】\n"
            f"{translation.text.strip()}\n\n"
            "【英文原文】\n"
            f"{english}"
        )
    if translation.status == "failed":
        if english.strip():
            return (
                "【中文翻譯暫時失敗,以下為英文原文】\n\n"
                "【英文原文】\n"
                f"{english}"
            )
        return "[無文字內容]"
    # noop (already-Chinese / URL-only) or ok with empty text: render once.
    if english.strip():
        return english
    return "[無文字內容]"


def _post_block(
    post: dict[str, Any],
    translation: TranslationResult | None = None,
) -> str:
    tier = str(post.get("tier") or "tier3").upper()
    kind = {
        "post": "原發文",
        "reply": "回覆",
        "retruth": "ReTruth",
    }.get(
        str(post.get("activity_type")),
        str(post.get("activity_type") or "發文"),
    )
    source_account = post.get("original_account")
    account_note = f"｜原帳號 @{source_account}" if source_account else ""
    media_count = int(post.get("media_count", 0) or 0)
    media_note = f"｜媒體附件 {media_count}" if media_count > 0 else ""
    header = (
        f"🇺🇸 Trump Truth Social｜{tier}\n"
        f"{_taipei_time(post.get('created_at'))}｜"
        f"{kind}{account_note}{media_note}"
    )
    english = post.get("text") or ""
    url = post.get("url") or ""
    if translation is None:
        # Translation disabled/unconfigured: keep the existing English-only
        # notification unchanged.
        return f"{header}\n{english or '[無文字內容]'}\n{url}".strip()
    body = _translated_body(english, translation)
    return f"{header}\n\n{body}\n\n{url}".strip()


def _split_long_block(
    block: str,
    max_chars: int = MAX_TELEGRAM_CHARS,
) -> list[str]:
    if len(block) <= max_chars:
        return [block]
    parts: list[str] = []
    remaining = block
    while remaining:
        if len(remaining) <= max_chars:
            parts.append(remaining)
            break
        cut = remaining.rfind("\n", 0, max_chars)
        if cut < max_chars // 2:
            cut = remaining.rfind(" ", 0, max_chars)
        if cut < max_chars // 2:
            cut = max_chars
        parts.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    return [
        f"{part}\n（第 {index}/{len(parts)} 段）"
        for index, part in enumerate(parts, 1)
    ]


def build_delivery_chunks(
    posts: list[dict[str, Any]],
    translations: dict[str, TranslationResult] | None = None,
) -> list[dict[str, Any]]:
    """Build chunks and mark a post complete only on its final fragment.

    ``translations`` maps post ID to its translation result. When absent (or a
    post is missing), the block renders the existing English-only notification.
    Chinese + full English are re-chunked together so a split never truncates.
    """
    ordered = sorted(
        posts,
        key=lambda item: _parse_time(item.get("created_at"))
        or datetime.min.replace(tzinfo=timezone.utc),
    )
    chunks: list[dict[str, Any]] = []
    current_parts: list[str] = []
    current_mark_posts: list[dict[str, Any]] = []
    current_length = 0
    current_audible = False

    def flush() -> None:
        nonlocal current_parts, current_mark_posts
        nonlocal current_length, current_audible
        if not current_parts:
            return
        chunks.append(
            {
                "message": "\n\n──────────\n\n".join(current_parts),
                "mark_posts": list(current_mark_posts),
                "audible": current_audible,
            }
        )
        current_parts = []
        current_mark_posts = []
        current_length = 0
        current_audible = False

    for post in ordered:
        translation = (
            translations.get(str(post.get("id") or ""))
            if translations
            else None
        )
        block_parts = _split_long_block(_post_block(post, translation))
        audible = post.get("tier") in {"tier1", "tier2"}
        for index, block in enumerate(block_parts):
            separator_len = 14 if current_parts else 0
            if (
                current_parts
                and current_length + separator_len + len(block)
                > MAX_TELEGRAM_CHARS
            ):
                flush()
            current_parts.append(block)
            if index == len(block_parts) - 1:
                current_mark_posts.append(post)
            current_length += separator_len + len(block)
            current_audible = current_audible or audible
    flush()
    return chunks


def _build_translations(
    posts: list[dict[str, Any]],
    translator: Any,
) -> tuple[dict[str, TranslationResult], dict[str, Any]]:
    """Translate each post once and return results plus public-safe health.

    The health dict carries only aggregates and a provider capability name —
    never post text, translation text or credentials.
    """
    counts = {
        "attempted": 0,
        "ok": 0,
        "noop": 0,
        "failed": 0,
        "budget_exhausted": 0,
        "fidelity_mismatch": 0,
    }
    translations: dict[str, TranslationResult] = {}
    if translator is None:
        health = {
            "translation_status": "unavailable",
            "translation_provider": None,
            "translation_attempted_count": 0,
            "translation_ok_count": 0,
            "translation_noop_count": 0,
            "translation_failed_count": 0,
            "translation_budget_exhausted_count": 0,
            "translation_fidelity_mismatch_count": 0,
        }
        return translations, health

    reset_translation_cache()
    budget = translation_config.TRANSLATION_RUN_BUDGET_SECONDS
    # Each provider call can run up to the per-call timeout, so to keep the
    # aggregate a *hard* bound we refuse to START a call unless the full
    # per-call budget still fits before the deadline. A call begun at
    # (deadline - per_call) finishes by the deadline; anything later is a
    # deterministic English fallback. This prevents a +59s call from
    # overrunning the 60s aggregate to ~79s.
    per_call = translation_config.TRANSLATION_TIMEOUT_MS / 1000.0
    deadline = _monotonic() + budget
    for post in posts:
        post_id = str(post.get("id") or "")
        if not post_id:
            continue
        text = post.get("text") or ""
        # No-op content never consumes the budget. For real translation work,
        # once the remaining budget can no longer safely fit a full provider
        # call, every remaining post gets a deterministic English fallback
        # instead, so a slow provider can never overrun the aggregate bound or
        # starve delivery of the whole batch.
        if not is_noop_text(text) and (deadline - _monotonic()) < per_call:
            result = TranslationResult(
                None, "failed", "budget", "budget_exhausted"
            )
        else:
            result = translate_text(text, translator)
        translations[post_id] = result
        if result.status == "noop":
            counts["noop"] += 1
        else:
            counts["attempted"] += 1
            if result.status == "ok":
                counts["ok"] += 1
            else:
                counts["failed"] += 1
                if result.error_code == "budget_exhausted":
                    counts["budget_exhausted"] += 1
                elif result.error_code == "fidelity_mismatch":
                    counts["fidelity_mismatch"] += 1

    # Separate "configured but not exercised" from "actually exercised": a
    # budget-exhausted post makes NO provider call, so it must not count as an
    # attempt, and a run that made zero provider calls is not "healthy" — it is
    # "not_run" (nothing was translated).
    provider_calls = counts["attempted"] - counts["budget_exhausted"]
    if counts["failed"]:
        status = "degraded"
    elif provider_calls > 0:
        status = "healthy"
    else:
        status = "not_run"
    health = {
        "translation_status": status,
        "translation_provider": getattr(translator, "name", "unknown"),
        # attempted == provider calls actually made (excludes budget-skips).
        "translation_attempted_count": provider_calls,
        "translation_provider_call_count": provider_calls,
        "translation_ok_count": counts["ok"],
        "translation_noop_count": counts["noop"],
        "translation_failed_count": counts["failed"],
        "translation_budget_exhausted_count": counts["budget_exhausted"],
        "translation_fidelity_mismatch_count": counts["fidelity_mismatch"],
    }
    return translations, health


def _should_send_unavailable_notice(previous: dict[str, Any]) -> bool:
    last = _parse_time(previous.get("last_unavailable_notice_at"))
    if last is None:
        return True
    return datetime.now(timezone.utc) - last >= UNAVAILABLE_NOTICE_COOLDOWN


def _completeness_note(result: dict[str, Any]) -> str:
    source = result.get("source")
    if source == "truth_social_official_api":
        return (
            "Direct official API polling is bounded and is not an audited "
            "complete historical feed; end-to-end completeness is unverified."
        )
    if source == "cnn_historical_archive":
        return (
            "Fresh mirror available; 100% parity with official Truth Social "
            "and recovery beyond the bounded source window are unverified."
        )
    return "No current source; completeness cannot be verified."


def _write_health(
    result: dict[str, Any],
    *,
    capture_started_at: datetime,
    eligible_count: int,
    timestamp_missing_count: int,
    new_count: int,
    archived_count: int,
    delivered_count: int,
    delivery_status: str,
    last_notice_at: str | None = None,
    translation_health: dict[str, Any] | None = None,
    delivery_health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw_count = result.get("raw_count")
    returned_count = result.get("returned_count")
    source_limit = result.get("source_limit")
    bounded = (
        isinstance(raw_count, int)
        and isinstance(returned_count, int)
        and raw_count > returned_count
    )
    health = {
        "status": result.get("status"),
        "source": result.get("source"),
        "latest_post_at": result.get("latest_post_at"),
        "attempts": result.get("attempts", []),
        "source_raw_count": raw_count,
        "source_returned_count": returned_count,
        "source_limit": source_limit,
        "source_window_bounded": bounded,
        "capture_started_at": capture_started_at.isoformat(),
        "initial_backfill_hours": int(
            INITIAL_BACKFILL_WINDOW.total_seconds() / 3600
        ),
        "eligible_count": eligible_count,
        "timestamp_missing_count": timestamp_missing_count,
        "new_count": new_count,
        "archived_count": archived_count,
        "delivered_count": delivered_count,
        "delivery_status": delivery_status,
        "delivery_requires_all_recipients": True,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "capture_policy": (
            "all_posts_replies_retruths_after_capture_checkpoint"
        ),
        "keyword_policy": (
            "tier_is_metadata_and_notification_urgency_only"
        ),
        # A direct endpoint is better than a mirror, but neither a bounded API
        # poll nor a bounded mirror window proves audited, gap-free completeness.
        "source_completeness_verified": False,
        "source_completeness_note": _completeness_note(result),
        "last_unavailable_notice_at": last_notice_at,
    }
    # Public-safe translation aggregates only: status, counts and provider
    # capability name. Never the post text, translation text or credentials.
    health.update(
        translation_health
        or {
            "translation_status": "not_run",
            "translation_provider": None,
            "translation_attempted_count": 0,
            "translation_ok_count": 0,
            "translation_noop_count": 0,
            "translation_failed_count": 0,
            "translation_budget_exhausted_count": 0,
            "translation_fidelity_mismatch_count": 0,
        }
    )
    # Public-safe delivery aggregates: per-run ambiguous/failed counts and the
    # durable ledger state counts (post IDs/states only, no text or chat IDs).
    if delivery_health:
        health.update(delivery_health)
    write_json(HEALTH_FILE, health)
    return health


def _deliver_post(
    post: dict[str, Any],
    translation: TranslationResult | None,
) -> str:
    """Send one post's fragments and return a durable delivery outcome.

    ``"sent"``      — every fragment reached every recipient.
    ``"failed"``    — nothing was delivered and every failure was a definitive
                      rejection, so re-sending the whole post is safe.
    ``"ambiguous"`` — a partial/unknown outbound (some recipients/fragments may
                      have gone out); the caller must quarantine it, never
                      blindly auto-retry (that would duplicate).
    """
    fragments = _split_long_block(_post_block(post, translation))
    audible = post.get("tier") in {"tier1", "tier2"}
    any_sent = False
    for fragment in fragments:
        outcome = send_telegram_detailed(
            fragment,
            parse_mode=None,
            disable_notification=not audible,
            # The message carries the translation + full English; redact the
            # Actions-log preview so neither is ever logged (§7).
            sensitive=True,
        ).get("outcome")
        if outcome == "sent":
            any_sent = True
            continue
        if outcome == "failed":
            # This fragment certainly did not go out. If earlier fragments did,
            # the post is partially delivered (ambiguous); otherwise nothing
            # went out and the whole post is safe to retry next run.
            return "ambiguous" if any_sent else "failed"
        return "ambiguous"  # partial across recipients / transport-unknown
    return "sent"


def _fail_closed_health(reason: str) -> None:
    """Write a minimal degraded health record without licensing a re-send."""
    write_json(
        HEALTH_FILE,
        {
            "status": "state_unreadable",
            "delivery_status": reason,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "source_completeness_verified": False,
        },
    )


def _attempt_id(run_id: str | None) -> str:
    """Unique per-workflow-attempt identity (run id + run attempt).

    A GitHub re-run reuses ``GITHUB_RUN_ID`` but bumps ``GITHUB_RUN_ATTEMPT``, so
    binding the durable claim/result to this composite identity stops a re-run
    from verifying (and thus trusting) a prior attempt's remote record.
    """
    run_attempt = os.getenv("GITHUB_RUN_ATTEMPT") or "1"
    return f"{run_id or 'local'}:{run_attempt}"


def _resync_authoritative(store: TrumpDeliveryStore) -> bool:
    """Restore origin's authoritative ledger over our dirty local copy.

    After a compare-and-set conflict or an undurable claim, the local ledger
    carries our uncommitted claim; hydrating discards it so the trailing
    commit-state never pushes a record that would clobber the authoritative one.
    Returns False (state unreadable) if origin can no longer be read.
    """
    try:
        hydrate_from_remote(store)
        return True
    except StateReadError as exc:
        logger.error(
            f"trump conflict resync failed ({type(exc).__name__}); workflow red"
        )
        return False


def _deliver_durably(
    store: TrumpDeliveryStore,
    post: dict[str, Any],
    translation: TranslationResult | None,
    *,
    run_id: str | None,
    attempt_id: str,
) -> str:
    """Claim (remote-verified) -> send -> resolve (remote-verified) for one post.

    Returns a durable outcome label:

    - ``sent`` / ``failed`` / ``ambiguous`` — the send result (see ``_deliver_post``).
    - ``skip_sent`` — origin already shows this post delivered (raced / re-run);
      not resent, not counted as a new delivery.
    - ``conflict_claim`` — a *foreign* attempt owns an unresolved claim; not sent.
    - ``claim_undurable`` — the claim could not be verified on origin; not sent
      (safe to retry next run).
    - ``state_unreadable`` — authoritative state could not be re-read on conflict.
    - ``state_persist_failed`` — the send happened but its terminal record could
      not be verified on origin (kept red so the next run does not misread it).

    In local/test mode (durable disabled) ``durable_push`` returns ``disabled``,
    so this reduces to the original claim -> send -> resolve with no git effects.
    """
    post_id = str(post.get("id") or "")
    if not post_id:
        return "skip_empty"
    if store.claim(post, run_id=run_id, attempt_id=attempt_id) is None:
        return "skip_sent"  # already 'sent' (raced/hydrated) — never resend

    claim_push = durable_push(
        store,
        f"trump claim {post_id} [skip ci]",
        expected={
            "post_id": post_id,
            "delivery_state": DELIVERY_CLAIMED,
            "workflow_attempt_id": attempt_id,
        },
        block_foreign_claim=True,
    )
    if claim_push == PUSH_CONFLICT_SENT:
        _resync_authoritative(store)
        return "skip_sent"
    if claim_push == PUSH_CONFLICT_CLAIM:
        return "conflict_claim" if _resync_authoritative(store) else "state_unreadable"
    if claim_push == PUSH_FAILED:
        # The claim is not durable on origin; sending now would risk a duplicate
        # on the next run. Do not send; restore authoritative state and retry later.
        return "claim_undurable" if _resync_authoritative(store) else "state_unreadable"

    # PUSH_OK (durable) or PUSH_DISABLED (local): the claim is durable enough.
    outcome = _deliver_post(post, translation)
    store.resolve(post_id, outcome, run_id=run_id, attempt_id=attempt_id)
    term_push = durable_push(
        store,
        f"trump {outcome} {post_id} [skip ci]",
        expected={
            "post_id": post_id,
            "delivery_state": outcome,
            "workflow_attempt_id": attempt_id,
        },
    )
    if term_push == PUSH_FAILED:
        return "state_persist_failed"
    return outcome


def _archive_retry_candidates(
    store: TrumpDeliveryStore,
    eligible: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Rebuild delivery candidates for undelivered ``pending``/``failed`` posts.

    A ``pending`` post (captured but not yet delivered — e.g. a mid-loop timeout
    before its per-post claim) or a definitively ``failed`` post that is still in
    the live-source window is retried via the normal eligible path; only those
    that have aged OUT of the bounded source window are recovered here from the
    authoritative archive (bounded, oldest first), so a captured-or-failed post
    is never silently lost once it leaves the source. Returns
    ``(retry_posts, missing_ids)`` where ``missing_ids`` are undelivered records
    whose archived payload cannot be recovered — the caller keeps the run red
    (fail closed), never green.

    ``get_archived_posts`` fails closed (raises ``ArchiveError``) on a
    corrupt-present archive.
    """
    undelivered_ids = store.ids_in_state(DELIVERY_PENDING) + store.ids_in_state(
        DELIVERY_FAILED
    )
    if not undelivered_ids:
        return [], []
    eligible_ids = {str(post.get("id") or "") for post in eligible}
    absent = [pid for pid in undelivered_ids if pid not in eligible_ids][
        :MAX_ARCHIVE_RETRY_PER_RUN
    ]
    if not absent:
        return [], []
    archived = get_archived_posts(absent)
    retry_posts = [archived[pid] for pid in absent if pid in archived]
    missing_ids = [pid for pid in absent if pid not in archived]
    return retry_posts, missing_ids


def _dedupe_ordered(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """De-duplicate by post id, keeping the first, then sort chronologically."""
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for post in posts:
        post_id = str(post.get("id") or "")
        if post_id and post_id not in seen:
            seen.add(post_id)
            unique.append(post)
    return sorted(
        unique,
        key=lambda item: _parse_time(item.get("created_at"))
        or datetime.min.replace(tzinfo=timezone.utc),
    )


def main() -> int:
    logger.info("=== run_trump_monitor start: all-post capture mode ===")
    previous = read_json(HEALTH_FILE, default={})
    if not isinstance(previous, dict):
        previous = {}
    translator = get_default_translator()
    run_id = os.getenv("GITHUB_RUN_ID") or None

    store = TrumpDeliveryStore()
    run_attempt_id = _attempt_id(run_id)
    try:
        # Hydrate origin's authoritative ledger AND archive BEFORE any delivery
        # decision: a stale event checkout (a queued scheduled run, or a re-run
        # started from a SHA predating the previous run's state commit) must never
        # show a delivered post as unseen and re-blast it. On a VERIFIED-absent
        # remote (genuine first run) the local files are reset to empty and the
        # legacy seen file is taken from authoritative origin/main — never the
        # stale checkout — so a rollout race cannot re-blast. A corrupt local OR
        # remote ledger/archive/legacy fails closed rather than reading as empty.
        bootstrapped = hydrate_from_remote(store)
        hydrate_archive_from_remote()
        if bootstrapped:
            hydrate_legacy_from_remote(store.legacy_path)
        store.migrate_legacy_seen()
        capture_started_at = _capture_started_at(store)
    except StateReadError as exc:
        # A corrupt/unreadable ledger (local or authoritative remote) or bootstrap
        # file must NOT be read as empty (which would re-blast the whole
        # checkpoint window). Fail closed and exit non-zero.
        logger.error(
            f"Trump delivery ledger unreadable; failing closed: {type(exc).__name__}"
        )
        _fail_closed_health("state_unreadable_fail_closed")
        return 1

    result = fetch_recent_posts_with_health()
    if result.get("status") != "healthy":
        notice_at = previous.get("last_unavailable_notice_at")
        if _should_send_unavailable_notice(previous):
            notice = (
                "⚠️ Trump Truth Social 監控目前無可用即時來源。\n"
                "官方 API 與鏡像均未通過新鮮度／可用性檢查；"
                "系統已停止假裝正常，請查看 "
                "trump_monitor_health.json。"
            )
            if send_telegram(
                notice,
                parse_mode=None,
                disable_notification=False,
            ):
                notice_at = datetime.now(timezone.utc).isoformat()
        _, translation_health = _build_translations([], translator)
        _write_health(
            result,
            capture_started_at=capture_started_at,
            eligible_count=0,
            timestamp_missing_count=0,
            new_count=0,
            archived_count=0,
            delivered_count=0,
            delivery_status="source_unavailable",
            last_notice_at=notice_at,
            translation_health=translation_health,
        )
        logger.error("Trump monitor unavailable: no current source")
        return 1

    source_posts = result.get("posts", []) or []
    eligible, timestamp_missing = _eligible_since_checkpoint(
        source_posts,
        capture_started_at,
    )
    try:
        # A post is delivered now only if the ledger says PROCEED (never tried)
        # or RETRY (previously definitively failed). SENT is skipped (done) and
        # AMBIGUOUS/CLAIMED are quarantined — never blindly resent.
        new_posts = [
            post
            for post in eligible
            if resolve_delivery_action(store.get(str(post.get("id") or "")))
            in (DO_PROCEED, DO_RETRY)
        ]
        # Rebuild delivery candidates for undelivered pending/failed posts that
        # have aged OUT of the bounded live-source window (the archive was
        # hydrated from authoritative origin during bootstrap above), so a
        # captured-or-failed post is never silently lost once it leaves the source.
        retry_posts, missing_failed = _archive_retry_candidates(store, eligible)
    except StateReadError as exc:
        logger.error(
            f"Trump delivery/archive state unreadable; failing closed: "
            f"{type(exc).__name__}"
        )
        _fail_closed_health("state_unreadable_fail_closed")
        return 1
    except ArchiveError as exc:
        logger.error(
            f"Trump archive fail-closed rebuilding retries ({type(exc).__name__})"
        )
        _fail_closed_health("archive_unavailable_fail_closed")
        return 1

    deliver_posts = _dedupe_ordered(new_posts + retry_posts)
    deliver_ids = [str(post.get("id") or "") for post in deliver_posts]

    def _backlog_open() -> tuple[dict[str, int], int]:
        counts = store.unresolved_backlog()
        # pending/claimed/ambiguous/failed all keep the workflow red until 'sent'
        # or operator-cleared; a record whose archived payload is missing is also
        # unresolved (fail closed rather than green).
        total = (
            counts[DELIVERY_PENDING]
            + counts[DELIVERY_CLAIMED]
            + counts[DELIVERY_AMBIGUOUS]
            + counts[DELIVERY_FAILED]
            + len(missing_failed)
        )
        return counts, total

    if not deliver_posts:
        _, translation_health = _build_translations([], translator)
        backlog, backlog_open = _backlog_open()
        status = "unresolved_delivery_backlog" if backlog_open else "no_new_posts"
        _write_health(
            result,
            capture_started_at=capture_started_at,
            eligible_count=len(eligible),
            timestamp_missing_count=timestamp_missing,
            new_count=0,
            archived_count=0,
            delivered_count=0,
            delivery_status=status,
            last_notice_at=previous.get("last_unavailable_notice_at"),
            translation_health=translation_health,
            delivery_health={
                "delivery_unresolved_backlog_count": backlog_open,
                "delivery_failed_backlog_count": backlog[DELIVERY_FAILED],
                "delivery_archive_missing_failed_count": len(missing_failed),
                "delivery_ledger_counts": store.health_counts(),
            },
        )
        if backlog_open:
            logger.error(
                f"Trump delivery backlog unresolved: {backlog_open} "
                "claimed/ambiguous/failed record(s); workflow red until cleared"
            )
            return 1
        logger.info("=== run_trump_monitor done: healthy, no new posts ===")
        return 0

    # Durably mark every newly-captured post 'pending' and archive it, then make
    # BOTH the archive rows and the pending ledger records durable + remote-
    # verified BEFORE any claim/send. This closes the mid-loop-timeout gap: a
    # captured post can never be archive-only with no ledger record. Every
    # non-terminal ledger ID is protected from archive pruning, so a still-owed
    # post's payload is never deleted (overflow fails closed instead). Retry posts
    # are already pending/failed + archived. Corrupt/write failure => red, no send.
    try:
        store.mark_pending(new_posts, run_id=run_id, attempt_id=run_attempt_id)
        protected = store.non_terminal_ids() | set(deliver_ids)
        archived_count = archive_posts(new_posts, protected_ids=protected)
    except ArchiveError as exc:
        logger.error(
            f"Trump archive fail-closed ({type(exc).__name__}); not sending"
        )
        _, translation_health = _build_translations([], translator)
        _write_health(
            result,
            capture_started_at=capture_started_at,
            eligible_count=len(eligible),
            timestamp_missing_count=timestamp_missing,
            new_count=len(new_posts),
            archived_count=0,
            delivered_count=0,
            delivery_status="archive_unavailable_fail_closed",
            last_notice_at=previous.get("last_unavailable_notice_at"),
            translation_health=translation_health,
            delivery_health={"delivery_ledger_counts": store.health_counts()},
        )
        return 1

    if (
        durable_push_capture(deliver_ids, "state: trump capture [skip ci]")
        == PUSH_FAILED
    ):
        # The archive is not durably on origin; sending now could deliver a post
        # a crash would leave unarchived. Fail closed (retryable next run).
        logger.error("Trump archive not durable on origin; not sending (retryable)")
        _, translation_health = _build_translations([], translator)
        _write_health(
            result,
            capture_started_at=capture_started_at,
            eligible_count=len(eligible),
            timestamp_missing_count=timestamp_missing,
            new_count=len(new_posts),
            archived_count=archived_count,
            delivered_count=0,
            delivery_status="archive_not_durable_fail_closed",
            last_notice_at=previous.get("last_unavailable_notice_at"),
            translation_health=translation_health,
            delivery_health={"delivery_ledger_counts": store.health_counts()},
        )
        return 1

    translations, translation_health = _build_translations(deliver_posts, translator)

    delivered_count = ambiguous_count = failed_count = 0
    blocked_count = 0  # foreign-claim / undurable-claim / unreadable / persist-fail
    for post in deliver_posts:
        # Each post is claimed durably (remote-verified in durable mode) BEFORE
        # its non-idempotent send, and its terminal result is remote-verified
        # after. A stale/raced/re-run checkout can never resend a delivered post.
        label = _deliver_durably(
            store,
            post,
            translations.get(str(post.get("id") or "")),
            run_id=run_id,
            attempt_id=run_attempt_id,
        )
        if label == "sent":
            delivered_count += 1
        elif label == "ambiguous":
            ambiguous_count += 1
        elif label == "failed":
            failed_count += 1
        elif label in ("skip_sent", "skip_empty"):
            continue  # already delivered elsewhere / no id — nothing to send
        else:
            # conflict_claim / claim_undurable / state_unreadable /
            # state_persist_failed: a non-durable, no-send condition kept red.
            blocked_count += 1

    backlog, backlog_open = _backlog_open()
    red = bool(blocked_count or backlog_open)
    if backlog[DELIVERY_CLAIMED] or backlog[DELIVERY_AMBIGUOUS]:
        delivery_status = "delivery_ambiguous"
    elif blocked_count:
        delivery_status = "delivery_blocked_not_durable"
    elif backlog[DELIVERY_FAILED] or backlog[DELIVERY_PENDING] or missing_failed:
        delivery_status = "delivery_undelivered_backlog"
    else:
        delivery_status = "delivered_all"
    _write_health(
        result,
        capture_started_at=capture_started_at,
        eligible_count=len(eligible),
        timestamp_missing_count=timestamp_missing,
        new_count=len(new_posts),
        archived_count=archived_count,
        delivered_count=delivered_count,
        delivery_status=delivery_status,
        last_notice_at=previous.get("last_unavailable_notice_at"),
        translation_health=translation_health,
        delivery_health={
            "delivery_ambiguous_count": ambiguous_count,
            "delivery_failed_count": failed_count,
            "delivery_blocked_count": blocked_count,
            "delivery_retried_from_archive_count": len(retry_posts),
            "delivery_unresolved_backlog_count": backlog_open,
            "delivery_pending_backlog_count": backlog[DELIVERY_PENDING],
            "delivery_failed_backlog_count": backlog[DELIVERY_FAILED],
            "delivery_archive_missing_failed_count": len(missing_failed),
            "delivery_requires_all_recipients": True,
            "delivery_ledger_counts": store.health_counts(),
        },
    )

    if red:
        logger.error(
            f"Trump delivery incomplete: {failed_count} failed, "
            f"{ambiguous_count} ambiguous, {blocked_count} blocked, "
            f"{backlog_open} unresolved backlog"
        )
        return 1

    logger.info(
        f"=== run_trump_monitor done: {len(deliver_posts)} to deliver, "
        f"{delivered_count} delivered ==="
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
