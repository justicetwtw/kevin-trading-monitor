"""Trump monitor must capture every current post and never fake health."""

from datetime import datetime, timedelta, timezone

from src.data import trump_truth
from src.runners import run_trump_monitor


def _post(
    post_id: str,
    text: str,
    *,
    hours_ago: int = 1,
    tier: str = "tier3",
    activity_type: str = "post",
):
    return {
        "id": post_id,
        "created_at": (
            datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        ).isoformat(),
        "url": f"https://truthsocial.com/@realDonaldTrump/{post_id}",
        "text": text,
        "activity_type": activity_type,
        "source": "truth_social_official_api",
        "original_account": "realDonaldTrump",
        "media_count": 0,
        "tier": tier,
        "matched_keywords": {"tier1": {}, "tier2": {}},
    }


def _healthy_result(posts, source="truth_social_official_api"):
    return {
        "status": "healthy",
        "source": source,
        "latest_post_at": posts[-1]["created_at"] if posts else None,
        "posts": posts,
        "attempts": [],
        "raw_count": len(posts),
        "returned_count": len(posts),
        "source_limit": trump_truth.SOURCE_POST_LIMIT,
    }


def test_official_current_source_wins_without_using_stale_mirror(monkeypatch):
    raw = {
        "id": "current-1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "content": "A post with no stock keyword at all",
        "url": "https://truthsocial.com/@realDonaldTrump/current-1",
    }
    monkeypatch.setattr(trump_truth, "fetch_from_truth_api", lambda: [raw])
    monkeypatch.setattr(
        trump_truth,
        "fetch_from_cnn_mirror",
        lambda: (_ for _ in ()).throw(
            AssertionError("fresh official source should stop fallback")
        ),
    )

    result = trump_truth.fetch_recent_posts_with_health()

    assert result["status"] == "healthy"
    assert result["source"] == "truth_social_official_api"
    assert result["posts"][0]["text"] == "A post with no stock keyword at all"
    assert result["posts"][0]["tier"] == "tier3"


def test_stale_cnn_archive_is_not_accepted_as_live(monkeypatch):
    monkeypatch.setattr(
        trump_truth,
        "fetch_from_truth_api",
        lambda: (_ for _ in ()).throw(RuntimeError("official unavailable")),
    )
    monkeypatch.setattr(
        trump_truth,
        "fetch_from_cnn_mirror",
        lambda: [
            {
                "id": "2023-old",
                "created_at": "2023-01-10T03:05:59Z",
                "text": "historical only",
            }
        ],
    )

    result = trump_truth.fetch_recent_posts_with_health()

    assert result["status"] == "unavailable"
    assert result["posts"] == []
    assert any(
        attempt["source"] == "cnn_historical_archive"
        and attempt["status"] == "stale"
        and attempt["latest_post_at"].startswith("2023-01-10")
        for attempt in result["attempts"]
    )


def test_huge_mirror_returns_only_latest_bounded_set(monkeypatch):
    now = datetime.now(timezone.utc)
    raw = [
        {
            "id": str(index),
            "created_at": (now - timedelta(minutes=index)).isoformat(),
            "text": f"post {index}",
        }
        for index in range(trump_truth.SOURCE_POST_LIMIT + 50)
    ]
    monkeypatch.setattr(
        trump_truth,
        "fetch_from_truth_api",
        lambda: (_ for _ in ()).throw(RuntimeError("official unavailable")),
    )
    monkeypatch.setattr(trump_truth, "fetch_from_cnn_mirror", lambda: raw)

    result = trump_truth.fetch_recent_posts_with_health()

    assert result["status"] == "healthy"
    assert result["source"] == "cnn_historical_archive"
    assert result["raw_count"] == trump_truth.SOURCE_POST_LIMIT + 50
    assert result["returned_count"] == trump_truth.SOURCE_POST_LIMIT
    assert len(result["posts"]) == trump_truth.SOURCE_POST_LIMIT
    assert result["posts"][0]["id"] == "0"
    assert result["posts"][-1]["id"] == str(
        trump_truth.SOURCE_POST_LIMIT - 1
    )


def test_retruth_text_and_activity_are_preserved():
    normalized = trump_truth.normalize_post(
        {
            "id": "outer-1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "content": "",
            "reblog": {
                "id": "inner-1",
                "content": "<p>Policy statement from another account</p>",
                "url": "https://truthsocial.com/@someone/inner-1",
                "account": {"acct": "someone"},
                "media_attachments": [{"id": "m1"}],
            },
        },
        "truth_social_official_api",
    )

    assert normalized["id"] == "outer-1"
    assert normalized["activity_type"] == "retruth"
    assert normalized["text"] == "Policy statement from another account"
    assert normalized["original_account"] == "someone"
    assert normalized["media_count"] == 1


def test_tier3_is_built_for_delivery_not_filtered():
    post = _post("tier3-1", "Happy birthday message", tier="tier3")
    chunks = run_trump_monitor.build_delivery_chunks([post])

    assert len(chunks) == 1
    assert "Happy birthday message" in chunks[0]["message"]
    assert "TIER3" in chunks[0]["message"]
    assert chunks[0]["audible"] is False
    assert chunks[0]["mark_posts"] == [post]


def test_tier1_and_tier3_both_delivered_in_same_poll(monkeypatch):
    posts = [
        _post("low", "Apparently unrelated post", tier="tier3"),
        _post("high", "New tariff policy", tier="tier1"),
    ]
    monkeypatch.setattr(
        run_trump_monitor,
        "fetch_recent_posts_with_health",
        lambda: _healthy_result(posts),
    )
    monkeypatch.setattr(run_trump_monitor, "get_unseen_posts", lambda value: value)
    monkeypatch.setattr(run_trump_monitor, "archive_posts", lambda value: len(value))
    seen = []
    monkeypatch.setattr(
        run_trump_monitor,
        "mark_posts_seen",
        lambda value: seen.extend(item["id"] for item in value),
    )
    sent = []
    monkeypatch.setattr(
        run_trump_monitor,
        "send_telegram",
        lambda message, **kwargs: sent.append((message, kwargs)) or True,
    )
    health = {}
    monkeypatch.setattr(run_trump_monitor, "read_json", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        run_trump_monitor,
        "write_json",
        lambda filename, value: health.setdefault(filename, value) is value,
    )

    assert run_trump_monitor.main() == 0
    joined = "\n".join(message for message, _ in sent)
    assert "Apparently unrelated post" in joined
    assert "New tariff policy" in joined
    assert sorted(seen) == ["high", "low"]
    state = health["trump_monitor_health.json"]
    assert state["delivery_status"] == "delivered_all"
    assert state["capture_policy"].startswith("all_posts")
    assert state["eligible_count"] == 2
    assert state["source_completeness_verified"] is True


def test_first_activation_backfills_24h_but_not_years_of_history(monkeypatch):
    recent = _post("recent", "current policy", hours_ago=2)
    historical = _post("old", "historical post", hours_ago=48)
    posts = [historical, recent]
    monkeypatch.setattr(
        run_trump_monitor,
        "fetch_recent_posts_with_health",
        lambda: _healthy_result(posts),
    )
    captured = []
    monkeypatch.setattr(
        run_trump_monitor,
        "get_unseen_posts",
        lambda value: captured.extend(value) or value,
    )
    monkeypatch.setattr(run_trump_monitor, "archive_posts", lambda value: len(value))
    monkeypatch.setattr(run_trump_monitor, "mark_posts_seen", lambda value: None)
    monkeypatch.setattr(run_trump_monitor, "send_telegram", lambda *a, **k: True)
    monkeypatch.setattr(run_trump_monitor, "read_json", lambda *a, **k: {})
    writes = {}
    monkeypatch.setattr(
        run_trump_monitor,
        "write_json",
        lambda filename, value: writes.setdefault(filename, value) is value,
    )

    assert run_trump_monitor.main() == 0
    assert [post["id"] for post in captured] == ["recent"]
    state = writes["trump_monitor_health.json"]
    assert state["initial_backfill_hours"] == 24
    assert state["eligible_count"] == 1


def test_existing_capture_checkpoint_is_reused(monkeypatch):
    checkpoint = datetime.now(timezone.utc) - timedelta(days=3)
    posts = [_post("two-days", "missed during downtime", hours_ago=48)]
    previous = {"capture_started_at": checkpoint.isoformat()}
    monkeypatch.setattr(
        run_trump_monitor,
        "fetch_recent_posts_with_health",
        lambda: _healthy_result(posts),
    )
    monkeypatch.setattr(run_trump_monitor, "get_unseen_posts", lambda value: value)
    monkeypatch.setattr(run_trump_monitor, "archive_posts", lambda value: len(value))
    monkeypatch.setattr(run_trump_monitor, "mark_posts_seen", lambda value: None)
    monkeypatch.setattr(run_trump_monitor, "send_telegram", lambda *a, **k: True)
    monkeypatch.setattr(run_trump_monitor, "read_json", lambda *a, **k: previous)
    writes = {}
    monkeypatch.setattr(
        run_trump_monitor,
        "write_json",
        lambda filename, value: writes.setdefault(filename, value) is value,
    )

    assert run_trump_monitor.main() == 0
    state = writes["trump_monitor_health.json"]
    assert state["eligible_count"] == 1
    assert state["capture_started_at"] == checkpoint.isoformat()


def test_source_unavailable_is_explicit_failure(monkeypatch):
    monkeypatch.setattr(
        run_trump_monitor,
        "fetch_recent_posts_with_health",
        lambda: {
            "status": "unavailable",
            "source": None,
            "posts": [],
            "latest_post_at": None,
            "attempts": [
                {
                    "source": "truth_social_official_api",
                    "status": "unavailable",
                    "error": "HTTPStatusError",
                }
            ],
        },
    )
    monkeypatch.setattr(run_trump_monitor, "read_json", lambda *args, **kwargs: {})
    monkeypatch.setattr(run_trump_monitor, "send_telegram", lambda *args, **kwargs: True)
    writes = {}
    monkeypatch.setattr(
        run_trump_monitor,
        "write_json",
        lambda filename, value: writes.setdefault(filename, value) is value,
    )

    assert run_trump_monitor.main() == 1
    health = writes["trump_monitor_health.json"]
    assert health["status"] == "unavailable"
    assert health["delivery_status"] == "source_unavailable"
    assert health["eligible_count"] == 0
    assert health["source_completeness_verified"] is False


def test_long_post_is_split_without_truncating_content_or_early_seen():
    text = "政策內容 " * 1200
    post = _post("long-1", text)
    chunks = run_trump_monitor.build_delivery_chunks([post])

    assert len(chunks) > 1
    delivered = "".join(chunk["message"] for chunk in chunks)
    assert delivered.count("政策內容") == text.count("政策內容")
    assert all(
        len(chunk["message"])
        <= run_trump_monitor.MAX_TELEGRAM_CHARS + 20
        for chunk in chunks
    )
    assert all(chunk["mark_posts"] == [] for chunk in chunks[:-1])
    assert chunks[-1]["mark_posts"] == [post]


def test_failed_middle_of_long_post_does_not_mark_seen(monkeypatch):
    post = _post("long-fail", "內容 " * 3000)
    result = _healthy_result([post])
    monkeypatch.setattr(
        run_trump_monitor,
        "fetch_recent_posts_with_health",
        lambda: result,
    )
    monkeypatch.setattr(run_trump_monitor, "get_unseen_posts", lambda value: value)
    monkeypatch.setattr(run_trump_monitor, "archive_posts", lambda value: len(value))
    marked = []
    monkeypatch.setattr(
        run_trump_monitor,
        "mark_posts_seen",
        lambda value: marked.extend(value),
    )
    calls = {"count": 0}

    def _send(*args, **kwargs):
        calls["count"] += 1
        return calls["count"] == 1

    monkeypatch.setattr(run_trump_monitor, "send_telegram", _send)
    monkeypatch.setattr(run_trump_monitor, "read_json", lambda *a, **k: {})
    monkeypatch.setattr(run_trump_monitor, "write_json", lambda *a, **k: True)

    assert run_trump_monitor.main() == 1
    assert marked == []
