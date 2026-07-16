"""Layer 0+.1 — classify every captured Trump Truth Social activity.

Classification is metadata, not a gate. Tier 3 posts are retained because a
post that appears unrelated to stocks can still affect war, policy, tariffs,
regulation, diplomacy or market sentiment.
"""

from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger

from src.config.position_mapping import map_event_to_positions
from src.data.trump_truth import (
    archive_posts,
    fetch_recent_posts_with_health,
    get_unseen_posts,
)
from src.storage.state_manager import write_json


def scan_and_classify() -> list[dict]:
    """Fetch, retain and classify all new posts; never suppress Tier 3."""
    result = fetch_recent_posts_with_health()
    posts = result.get("posts", []) if isinstance(result, dict) else []
    new_posts = get_unseen_posts(posts)

    classified = []
    for post in new_posts:
        try:
            matched = post.get("matched_keywords") or {}
            classified.append(
                {
                    **post,
                    "events": map_event_to_positions(matched),
                    "scan_time": datetime.now(timezone.utc).isoformat(),
                }
            )
        except Exception as exc:
            logger.warning(f"Trump classifier per-post failed: {exc}")
            classified.append(
                {
                    **post,
                    "events": [],
                    "scan_time": datetime.now(timezone.utc).isoformat(),
                    "classification_error": type(exc).__name__,
                }
            )

    if classified:
        archive_posts(classified)

    write_json(
        "layer_trump_classifier_state.json",
        {
            "classified": classified,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source_status": result.get("status") if isinstance(result, dict) else "unavailable",
            "source": result.get("source") if isinstance(result, dict) else None,
            "latest_post_at": result.get("latest_post_at") if isinstance(result, dict) else None,
            "attempts": result.get("attempts", []) if isinstance(result, dict) else [],
            "filter_policy": "retain_all_posts_tier_is_metadata_only",
        },
    )
    return classified
