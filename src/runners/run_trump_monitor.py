"""Capture and deliver every new Donald Trump Truth Social activity.

No keyword filter is allowed to decide whether a post is captured or delivered.
Tier classification only controls notification urgency and downstream tagging.
If no current source is available, this runner writes an explicit unavailable
health state, sends a throttled warning and exits non-zero.
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


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = isoparse(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (TypeError, ValueError, OverflowError):
        return None


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
    }.get(str(post.get("activity_type")), str(post.get("activity_type") or "發文"))
    source_account = post.get("original_account")
    account_note = f"｜原帳號 @{source_account}" if source_account else ""
    media_note = (
        f"｜媒體附件 {post.get('media_count')}"
        if int(post.get("media_count", 0) or 0) > 0
        else ""
    )
    return (
        f"🇺🇸 Trump Truth Social｜{tier}\n"
        f"{_taipei_time(post.get('created_at'))}｜{kind}{account_note}{media_note}\n"
        f"{post.get('text') or '[無文字內容]'}\n"
        f"{post.get('url') or ''}"
    ).strip()


def _split_long_block(block: str, max_chars: int = MAX_TELEGRAM_CHARS) -> list[str]:
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


def build_delivery_chunks(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build ordered Telegram chunks while retaining post IDs per chunk."""
    ordered = sorted(
        posts,
        key=lambda item: _parse_time(item.get("created_at"))
        or datetime.min.replace(tzinfo=timezone.utc),
    )
    chunks: list[dict[str, Any]] = []
    current_parts: list[str] = []
    current_posts: list[dict[str, Any]] = []
    current_length = 0
    current_audible = False

    def flush() -> None:
        nonlocal current_parts, current_posts, current_length, current_audible
        if not current_parts:
            return
        chunks.append(
            {
                "message": "\n\n──────────\n\n".join(current_parts),
                "posts": list(current_posts),
                "audible": current_audible,
            }
        )
        current_parts = []
        current_posts = []
        current_length = 0
        current_audible = False

    for post in ordered:
        block_parts = _split_long_block(_post_block(post))
        audible = post.get("tier") in {"tier1", "tier2"}
        for block in block_parts:
            separator_len = 14 if current_parts else 0
            if current_parts and current_length + separator_len + len(block) > MAX_TELEGRAM_CHARS:
                flush()
            current_parts.append(block)
            if post not in current_posts:
                current_posts.append(post)
            current_length += separator_len + len(block)
            current_audible = current_audible or audible
    flush()
    return chunks


def _should_send_unavailable_notice(previous: dict[str, Any]) -> bool:
    last = _parse_time(previous.get("last_unavailable_notice_at"))
    if last is None:
        return True
    return datetime.now(timezone.utc) - last >= UNAVAILABLE_NOTICE_COOLDOWN


def _write_health(
    result: dict[str, Any],
    *,
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
        "fetched_count": len(result.get("posts", []) or []),
        "new_count": new_count,
        "archived_count": archived_count,
        "delivered_count": delivered_count,
        "delivery_status": delivery_status,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "capture_policy": "all_posts_replies_retruths_no_keyword_filter",
        "keyword_policy": "tier_is_metadata_and_notification_urgency_only",
        "last_unavailable_notice_at": last_notice_at,
    }
    write_json(HEALTH_FILE, health)
    return health


def main() -> int:
    logger.info("=== run_trump_monitor start: all-post capture mode ===")
    previous = read_json(HEALTH_FILE, default={})
    if not isinstance(previous, dict):
        previous = {}

    result = fetch_recent_posts_with_health()
    if result.get("status") != "healthy":
        notice_at = previous.get("last_unavailable_notice_at")
        if _should_send_unavailable_notice(previous):
            notice = (
                "⚠️ Trump Truth Social 監控目前無可用即時來源。\n"
                "官方 API 與備援均未通過新鮮度／可用性檢查；"
                "系統已停止假裝正常，請查看 trump_monitor_health.json。"
            )
            if send_telegram(
                notice,
                parse_mode=None,
                disable_notification=False,
            ):
                notice_at = datetime.now(timezone.utc).isoformat()
        _write_health(
            result,
            new_count=0,
            archived_count=0,
            delivered_count=0,
            delivery_status="source_unavailable",
            last_notice_at=notice_at,
        )
        logger.error("Trump monitor unavailable: no current source")
        return 1

    posts = result.get("posts", []) or []
    new_posts = get_unseen_posts(posts)
    if not new_posts:
        _write_health(
            result,
            new_count=0,
            archived_count=0,
            delivered_count=0,
            delivery_status="no_new_posts",
            last_notice_at=previous.get("last_unavailable_notice_at"),
        )
        logger.info("=== run_trump_monitor done: healthy, no new posts ===")
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
        mark_posts_seen(chunk["posts"])
        delivered_count += len(chunk["posts"])

    delivery_status = "delivered_all" if not failed else "delivery_failed_partial"
    _write_health(
        result,
        new_count=len(new_posts),
        archived_count=archived_count,
        delivered_count=delivered_count,
        delivery_status=delivery_status,
        last_notice_at=previous.get("last_unavailable_notice_at"),
    )

    if failed:
        logger.error("Trump delivery failed; undelivered posts remain unseen for retry")
        return 1

    logger.info(
        f"=== run_trump_monitor done: {len(new_posts)} captured, "
        f"{delivered_count} delivered ==="
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
