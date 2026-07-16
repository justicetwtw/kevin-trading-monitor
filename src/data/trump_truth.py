"""Donald Trump Truth Social ingestion with explicit source health.

The official public API is attempted first. A broad CNN archive may be used as
a current mirror only when its newest timestamp is demonstrably fresh. Because
the mirror contains years of history, only its newest bounded activity set is
returned to the monitor; the runner separately establishes a capture-start
checkpoint so first activation cannot flood Telegram with historical posts.

Classification is metadata only. No keyword filter removes a post.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from dateutil.parser import isoparse
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config.keywords import classify_post, get_matched_keywords
from src.config.rss_sources import TRUMP_TRUTH_SOURCES
from src.storage.state_manager import read_json, write_json

SEEN_POSTS_FILE = "trump_seen_posts.json"
ARCHIVE_FILE = "trump_posts_archive.json"
MAX_SEEN = 10000
MAX_ARCHIVE = 5000
SOURCE_POST_LIMIT = 1000
LIVE_MAX_AGE = timedelta(days=7)
MIRROR_MAX_AGE = timedelta(hours=48)
HTTP_TIMEOUT = 20.0


class TrumpSourceError(RuntimeError):
    """A live source could not provide a valid current response."""


@retry(
    retry=retry_if_exception_type(
        (httpx.HTTPError, ValueError, TrumpSourceError)
    ),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=6),
    reraise=True,
)
def _get_json(url: str, params: dict[str, Any] | None = None) -> Any:
    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        response = client.get(
            url,
            params=params,
            headers={
                "User-Agent": "kevin-trading-monitor/1.0 public-feed-check",
                "Accept": "application/json",
            },
        )
        response.raise_for_status()
        return response.json()


def fetch_truth_account_id() -> str:
    """Resolve the account ID, falling back to the configured known ID."""
    configured = str(TRUMP_TRUTH_SOURCES["configured_account_id"])
    try:
        payload = _get_json(TRUMP_TRUTH_SOURCES["truth_account_lookup"])
        account_id = (
            str(payload.get("id") or "")
            if isinstance(payload, dict)
            else ""
        )
        return account_id or configured
    except Exception as exc:
        logger.warning(
            f"Truth account lookup failed; using configured ID: {exc}"
        )
        return configured


def fetch_from_truth_api() -> list[dict[str, Any]]:
    """Fetch current activity from the official public statuses API."""
    account_id = fetch_truth_account_id()
    url = TRUMP_TRUTH_SOURCES["truth_statuses_template"].format(
        account_id=account_id
    )
    payload = _get_json(
        url,
        params={
            "limit": 40,
            "exclude_replies": "false",
            "exclude_reblogs": "false",
        },
    )
    if not isinstance(payload, list):
        raise TrumpSourceError("Truth statuses response is not a list")
    return [item for item in payload if isinstance(item, dict)]


def fetch_from_cnn_mirror() -> list[dict[str, Any]]:
    """Fetch the broad CNN archive; freshness is validated separately."""
    payload = _get_json(TRUMP_TRUTH_SOURCES["cnn_historical_archive"])
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        posts = payload.get("posts", [])
        return [item for item in posts if isinstance(item, dict)]
    raise TrumpSourceError("CNN archive response has unsupported shape")


def _strip_html(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    try:
        from selectolax.parser import HTMLParser

        return HTMLParser(text).text(separator="\n", strip=True)
    except Exception:
        return text


def extract_text(post: dict[str, Any]) -> str:
    """Extract complete visible text, including nested re-truth content."""
    reblog = post.get("reblog")
    if isinstance(reblog, dict):
        nested = extract_text(reblog)
        outer = _strip_html(post.get("content"))
        return "\n".join(
            part for part in (outer, nested) if part
        ).strip()

    for key in ("content", "text", "body", "message"):
        value = post.get(key)
        if value:
            return _strip_html(value).strip()
    return ""


def _created_at(post: dict[str, Any]) -> str:
    value = (
        post.get("created_at")
        or post.get("timestamp")
        or post.get("date")
    )
    return str(value or "")


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = isoparse(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _select_latest_raw_posts(
    raw_posts: list[dict[str, Any]],
    limit: int = SOURCE_POST_LIMIT,
) -> list[dict[str, Any]]:
    """Select latest timestamped activities from a potentially huge archive."""
    ranked: list[tuple[datetime, dict[str, Any]]] = []
    for item in raw_posts:
        if not isinstance(item, dict):
            continue
        timestamp = _parse_timestamp(_created_at(item))
        if timestamp is not None:
            ranked.append((timestamp, item))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in ranked[:limit]]


def normalize_post(
    post: dict[str, Any], source: str
) -> dict[str, Any]:
    """Normalize one Truth activity without deciding whether it matters."""
    reblog = (
        post.get("reblog")
        if isinstance(post.get("reblog"), dict)
        else None
    )
    payload = reblog or post
    post_id = str(
        post.get("id")
        or post.get("post_id")
        or payload.get("id")
        or ""
    )
    text = extract_text(post)
    created_at = _created_at(post) or _created_at(payload)
    url = str(
        post.get("url")
        or payload.get("url")
        or (
            f"https://truthsocial.com/@realDonaldTrump/{post_id}"
            if post_id
            else TRUMP_TRUTH_SOURCES["truth_profile"]
        )
    )
    account = (
        payload.get("account")
        if isinstance(payload.get("account"), dict)
        else {}
    )
    media = payload.get("media_attachments")
    media_count = len(media) if isinstance(media, list) else 0
    activity_type = (
        "retruth"
        if reblog
        else ("reply" if post.get("in_reply_to_id") else "post")
    )

    return {
        "id": post_id,
        "created_at": created_at,
        "url": url,
        "text": text,
        "activity_type": activity_type,
        "source": source,
        "original_account": (
            account.get("acct") or account.get("username")
        ),
        "media_count": media_count,
        "tier": classify_post(text),
        "matched_keywords": get_matched_keywords(text),
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }


def _latest_post_at(
    posts: list[dict[str, Any]],
) -> datetime | None:
    values = [
        _parse_timestamp(post.get("created_at")) for post in posts
    ]
    valid = [value for value in values if value is not None]
    return max(valid) if valid else None


def _source_result(
    *,
    source: str,
    raw_posts: list[dict[str, Any]],
    max_age: timedelta,
) -> dict[str, Any]:
    raw_count = len(raw_posts)
    selected = _select_latest_raw_posts(raw_posts)
    normalized = [
        normalize_post(item, source)
        for item in selected
        if isinstance(item, dict)
    ]
    normalized = [
        item
        for item in normalized
        if item["id"]
        and item["text"]
        and _parse_timestamp(item.get("created_at")) is not None
    ]
    normalized.sort(
        key=lambda item: _parse_timestamp(item.get("created_at"))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    latest = _latest_post_at(normalized)
    now = datetime.now(timezone.utc)

    common = {
        "source": source,
        "raw_count": raw_count,
        "returned_count": len(normalized),
        "source_limit": SOURCE_POST_LIMIT,
    }
    if not normalized:
        return {
            **common,
            "status": "unavailable",
            "posts": [],
            "latest_post_at": None,
            "error": "source_returned_no_usable_timestamped_posts",
        }
    if latest is None:
        return {
            **common,
            "status": "stale",
            "posts": [],
            "latest_post_at": None,
            "error": "source_posts_missing_timestamps",
        }
    if now - latest > max_age:
        return {
            **common,
            "status": "stale",
            "posts": [],
            "latest_post_at": latest.isoformat(),
            "error": "latest_post_too_old_for_live_monitor",
        }
    return {
        **common,
        "status": "healthy",
        "posts": normalized,
        "latest_post_at": latest.isoformat(),
        "error": None,
    }


def _attempt_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in result.items()
        if key != "posts"
    }


def fetch_recent_posts_with_health() -> dict[str, Any]:
    """Return current posts plus transparent source-attempt metadata."""
    attempts: list[dict[str, Any]] = []

    try:
        official = _source_result(
            source="truth_social_official_api",
            raw_posts=fetch_from_truth_api(),
            max_age=LIVE_MAX_AGE,
        )
    except Exception as exc:
        official = {
            "status": "unavailable",
            "source": "truth_social_official_api",
            "posts": [],
            "latest_post_at": None,
            "raw_count": 0,
            "returned_count": 0,
            "source_limit": SOURCE_POST_LIMIT,
            "error": type(exc).__name__,
        }
    attempts.append(_attempt_summary(official))
    if official["status"] == "healthy":
        return {**official, "attempts": attempts}

    try:
        mirror = _source_result(
            source="cnn_historical_archive",
            raw_posts=fetch_from_cnn_mirror(),
            max_age=MIRROR_MAX_AGE,
        )
    except Exception as exc:
        mirror = {
            "status": "unavailable",
            "source": "cnn_historical_archive",
            "posts": [],
            "latest_post_at": None,
            "raw_count": 0,
            "returned_count": 0,
            "source_limit": SOURCE_POST_LIMIT,
            "error": type(exc).__name__,
        }
    attempts.append(_attempt_summary(mirror))
    if mirror["status"] == "healthy":
        return {**mirror, "attempts": attempts, "fallback": True}

    return {
        "status": "unavailable",
        "source": None,
        "posts": [],
        "latest_post_at": None,
        "raw_count": 0,
        "returned_count": 0,
        "source_limit": SOURCE_POST_LIMIT,
        "error": "no_current_trump_source_available",
        "attempts": attempts,
    }


def fetch_recent_posts() -> list[dict[str, Any]]:
    """Compatibility wrapper; use health-aware fetch in runners."""
    return fetch_recent_posts_with_health().get("posts", [])


def load_seen_ids() -> set[str]:
    seen = read_json(SEEN_POSTS_FILE, default={})
    if not isinstance(seen, dict):
        return set()
    return {str(key) for key in seen}


def get_unseen_posts(
    posts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    seen = load_seen_ids()
    return [
        post
        for post in posts
        if str(post.get("id") or "") not in seen
    ]


def mark_posts_seen(posts: list[dict[str, Any]]) -> None:
    seen = read_json(SEEN_POSTS_FILE, default={})
    if not isinstance(seen, dict):
        seen = {}
    now = datetime.now(timezone.utc).isoformat()
    for post in posts:
        post_id = str(post.get("id") or "")
        if not post_id:
            continue
        seen[post_id] = {
            "seen_at": now,
            "created_at": post.get("created_at"),
            "source": post.get("source"),
        }
    if len(seen) > MAX_SEEN:
        ordered = sorted(
            seen.items(),
            key=lambda item: str(item[1].get("seen_at") or ""),
        )
        seen = dict(ordered[-MAX_SEEN:])
    write_json(SEEN_POSTS_FILE, seen)


def filter_new_posts(
    posts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Legacy helper: return unseen posts and mark them immediately."""
    new_posts = get_unseen_posts(posts)
    mark_posts_seen(new_posts)
    return new_posts


def archive_posts(posts: list[dict[str, Any]]) -> int:
    """Store every captured post in a rolling archive, deduplicated by ID."""
    archive = read_json(ARCHIVE_FILE, default={})
    if not isinstance(archive, dict):
        archive = {}
    before = len(archive)
    for post in posts:
        post_id = str(post.get("id") or "")
        if post_id:
            archive[post_id] = post
    if len(archive) > MAX_ARCHIVE:
        ordered = sorted(
            archive.items(),
            key=lambda item: str(
                item[1].get("created_at")
                or item[1].get("captured_at")
                or ""
            ),
        )
        archive = dict(ordered[-MAX_ARCHIVE:])
    write_json(ARCHIVE_FILE, archive)
    return len(archive) - before


def classify_and_enrich(
    post: dict[str, Any],
) -> dict[str, Any]:
    """Compatibility helper that never drops Tier 3 posts."""
    if "tier" in post and "text" in post:
        return post
    return normalize_post(post, "unknown")


def fetch_and_classify_new() -> list[dict[str, Any]]:
    result = fetch_recent_posts_with_health()
    posts = get_unseen_posts(result.get("posts", []))
    return [classify_and_enrich(post) for post in posts]
