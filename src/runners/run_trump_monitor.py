"""Capture and deliver every new Donald Trump Truth Social activity.

No keyword filter decides whether a post is captured or delivered. Tier only
controls notification urgency. On first activation, the monitor establishes a
24-hour backfill checkpoint; this captures recent context without treating the
mirror's multi-year archive as thousands of new posts. A split long post is
marked seen only after its final chunk succeeds.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from typing import Any

from dateutil.parser import isoparse
from loguru import logger

from src.alerts.telegram_bot import send_telegram
from src.config.market_clock import TAIPEI
from src.data.trump_truth import (
    archive_posts,
    fetch_recent_posts_with_health,
    get_unseen_posts,
    mark_posts_seen,
)
from src.storage.state_manager import read_json, write_json

HEALTH_FILE = "trump_monitor_health.json"
MAX_TELEGRAM_CHARS = 3600
UNAVAILABLE_NOTICE_COOLDOWN = timedelta(hours=6)
INITIAL_BACKFILL_WINDOW = timedelta(hours=24)


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


def _capture_started_at(previous: dict[str, Any]) -> datetime:
    existing = _parse_time(previous.get("capture_started_at"))
    if existing is not None:
        return existing
    return datetime.now(timezone.utc) - INITIAL_BACKFILL_WINDOW


def _eligible_since_checkpoint(
    posts: list[dict[str, Any]],
    capture_started_at: datetime,
) -> tuple[list[dict[str, Any]], int]:
    """Exclude historical archive rows and count timestamp-invalid activities."""
    eligible = []
    missing_timestamp = 0
    for post in posts:
        created = _parse_time(post.get("created_at"))
        if created is None:
            missing_timestamp += 1
            continue
        if created >= capture_started_at:
            eligible.append(post)
    return eligible, missing_timestamp


def _taipei_time(value: Any) -> str:
    parsed = _parse_time(value)
    if parsed is None:
        return "時間未知"
    return parsed.astimezone(TAIPEI).strftime("%Y-%m-%d %H:%M 台北")


def _post_block(post: dict[str, Any]) -> str:
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
    account_note = (
        f"｜原帳號 @{source_account}" if source_account else ""
    )
    media_note = (
        f"｜媒體附件 {post.get('media_count')}"
        if int(post.get("media_count", 0) or 0) > 0
        else ""
    )
    return (
        f"🇺🇸 Trump Truth Social｜{tier}\n"
        f"{_taipei_time(post.get('created_at'))}｜"
        f"{kind}{account_note}{media_note}\n"
        f"{post.get('text') or '[無文字內容]'}\n"
        f"{post.get('url') or ''}"
    ).strip()


def _split_long_block(
    block: str,
    max_chars: int = MAX_TELEGRAM_CHARS,
) -> list[str]:
    if len(block) <= max_chars:
        return [block]
    parts = []
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
) -> list[dict[str, Any]]:
    """Build chunks and mark a post complete only on its final fragment."""
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
        block_parts = _split_long_block(_post_block(post))
        audible = post.get("tier") in {"tier1", "tier2"}
        for index, block in enumerate(block_parts):
            separator_len = 14 if current_parts else 0
            projected = current_length + separator_len + len(block)
            if current_parts and projected > MAX_TELEGRAM_CHARS:
                flush()
            current_parts.append(block)
            if index == len(block_parts) - 1:
                current_mark_posts.append(post)
            current_length += separator_len + len(block)
            current_audible = current_audible or audible
    flush()
    return chunks


def _should_send_unavailable_notice(
    previous: dict[str, Any],
) -> bool:
    last = _parse_time(previous.get("last_unavailable_notice_at"))
    if last is None:
        return True
    return (
        datetime.now(timezone.utc) - last
        >= UNAVAILABLE_NOTICE_COOLDOWN
    )


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
) -> dict[str, Any]:
    health = {
        "status": result.get("status"),
        "source": result.get("source"),
        "latest_post_at": result.get("latest_post_at"),
        "attempts": result.get("attempts", []),
        "source_raw_count": result.get("raw_count"),
        "source_returned_count": result.get("returned_count"),
        "source_limit": result.get("source_limit"),
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
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "capture_policy": (
            "all_posts_replies_retruths_after_capture_checkpoint"
        ),
        "keyword_policy": (
            "tier_is_metadata_and_notification_urgency_only"
        ),
        "source_completeness_verified": (
            result.get("source") == "truth_social_official_api"
        ),
        "source_completeness_note": (
            "Official public API response"
            if result.get("source") == "truth_social_official_api"
            else "Fresh mirror available; 100% parity with official Truth Social is not independently verified"
        ),
        "last_unavailable_notice_at": last_notice_at,
    }
    write_json(HEALTH_FILE, health)
    return health


def main() -> int:
    logger.info("=== run_trump_monitor start: all-post capture mode ===")
    previous = read_json(HEALTH_FILE, default={})
    if not isinstance(previous, dict):
        previous = {}
    capture_started_at = _capture_started_at(previous)

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
        )
        logger.error("Trump monitor unavailable: no current source")
        return 1

    source_posts = result.get("posts", []) or []
    eligible, timestamp_missing = _eligible_since_checkpoint(
        source_posts,
        capture_started_at,
    )
    new_posts = get_unseen_posts(eligible)
    if not new_posts:
        _write_health(
            result,
            capture_started_at=capture_started_at,
            eligible_count=len(eligible),
            timestamp_missing_count=timestamp_missing,
            new_count=0,
            archived_count=0,
            delivered_count=0,
            delivery_status="no_new_posts",
            last_notice_at=previous.get(
                "last_unavailable_notice_at"
            ),
        )
        logger.info(
            "=== run_trump_monitor done: healthy, no new posts ==="
        )
        return 0

    archived_count = archive_posts(new_posts)
    delivered_count = 0
    failed = False
    for chunk in build_delivery_chunks(new_posts):
        ok = send_telegram(
            chunk["message"],
            parse_mode=None,
            disable_notification=not bool(chunk["audible"]),
        )
        if not ok:
            failed = True
            break
        completed_posts = chunk["mark_posts"]
        if completed_posts:
            mark_posts_seen(completed_posts)
            delivered_count += len(completed_posts)

    delivery_status = (
        "delivered_all" if not failed else "delivery_failed_partial"
    )
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
    )

    if failed:
        logger.error(
            "Trump delivery failed; incomplete posts remain unseen"
        )
        return 1

    logger.info(
        f"=== run_trump_monitor done: {len(new_posts)} captured, "
        f"{delivered_count} delivered ==="
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
