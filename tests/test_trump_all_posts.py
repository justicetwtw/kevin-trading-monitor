"""Trump monitor must capture every current post and never fake health."""

import os
import tempfile
from datetime import datetime, timedelta, timezone

from src.data import trump_truth
from src.runners import run_trump_monitor
from src.storage.trump_delivery_state import TrumpDeliveryStore


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


def _temp_ledger_path():
    return os.path.join(tempfile.mkdtemp(), "trump_delivery_state.json")


def _fresh_store(state):
    """A fresh store over the same temp ledger — models a new process/run."""
    return TrumpDeliveryStore(path=state["ledger_path"], legacy_path=None)


def _delivered_ids(state):
    posts = _fresh_store(state)._read_raw()["posts"]
    return sorted(
        pid
        for pid, rec in posts.items()
        if rec.get("delivery_state") == "sent"
    )


def _ledger_state(state, post_id):
    rec = _fresh_store(state).get(post_id)
    return rec.get("delivery_state") if rec else None


def _patch_successful_runner(monkeypatch, posts, *, checkpoint=None, outcome="sent"):
    ledger_path = _temp_ledger_path()
    state = {"sent": [], "writes": {}, "ledger_path": ledger_path}
    if checkpoint is not None:
        TrumpDeliveryStore(
            path=ledger_path, legacy_path=None
        ).set_capture_started_at(checkpoint)
    monkeypatch.setattr(
        run_trump_monitor,
        "fetch_recent_posts_with_health",
        lambda: _healthy_result(posts),
    )
    monkeypatch.setattr(
        run_trump_monitor,
        "TrumpDeliveryStore",
        lambda: TrumpDeliveryStore(path=ledger_path, legacy_path=None),
    )
    monkeypatch.setattr(run_trump_monitor, "archive_posts", lambda value, **k: len(value))
    monkeypatch.setattr(
        run_trump_monitor,
        "send_telegram_detailed",
        lambda message, **kwargs: state["sent"].append((message, kwargs))
        or {"outcome": outcome, "delivered": 1, "total": 1},
    )
    monkeypatch.setattr(run_trump_monitor, "send_telegram", lambda *a, **k: True)
    monkeypatch.setattr(run_trump_monitor, "get_default_translator", lambda: None)
    monkeypatch.setattr(run_trump_monitor, "read_json", lambda *a, **k: {})
    monkeypatch.setattr(
        run_trump_monitor,
        "write_json",
        lambda filename, value: state["writes"].__setitem__(filename, value)
        or True,
    )
    return state


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


def test_tier1_and_tier3_both_delivered_and_completeness_not_overstated(
    monkeypatch,
):
    posts = [
        _post("low", "Apparently unrelated post", tier="tier3"),
        _post("high", "New tariff policy", tier="tier1"),
    ]
    state = _patch_successful_runner(monkeypatch, posts)

    assert run_trump_monitor.main() == 0
    joined = "\n".join(message for message, _ in state["sent"])
    assert "Apparently unrelated post" in joined
    assert "New tariff policy" in joined
    assert _delivered_ids(state) == ["high", "low"]
    health = state["writes"]["trump_monitor_health.json"]
    assert health["delivery_status"] == "delivered_all"
    assert health["capture_policy"].startswith("all_posts")
    assert health["source_completeness_verified"] is False
    assert health["delivery_requires_all_recipients"] is True
    assert "unverified" in health["source_completeness_note"]


def test_first_activation_backfills_24h_but_not_history(monkeypatch):
    recent = _post("recent", "current policy", hours_ago=2)
    historical = _post("old", "historical post", hours_ago=48)
    posts = [historical, recent]
    state = _patch_successful_runner(monkeypatch, posts)

    assert run_trump_monitor.main() == 0
    # A first activation backfills only 24h: the 48h historical post is not
    # eligible, so only the recent post is captured and delivered.
    assert _delivered_ids(state) == ["recent"]
    health = state["writes"]["trump_monitor_health.json"]
    assert health["initial_backfill_hours"] == 24
    assert health["eligible_count"] == 1


def test_existing_capture_checkpoint_is_reused(monkeypatch):
    checkpoint = datetime.now(timezone.utc) - timedelta(days=3)
    posts = [_post("two-days", "missed during downtime", hours_ago=48)]
    # The checkpoint now lives in the fail-closed delivery ledger, not the
    # fail-open health file; seed it there and confirm it is reused (a 48h post
    # remains eligible because the checkpoint is 3 days back, not 24h).
    state = _patch_successful_runner(
        monkeypatch, posts, checkpoint=checkpoint.isoformat()
    )

    assert run_trump_monitor.main() == 0
    health = state["writes"]["trump_monitor_health.json"]
    assert health["eligible_count"] == 1
    assert health["capture_started_at"] == checkpoint.isoformat()


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
    # Use a temp ledger so main()'s legacy migration never touches the real
    # data_store/ (tests must not write repo state).
    monkeypatch.setattr(
        run_trump_monitor,
        "TrumpDeliveryStore",
        lambda: TrumpDeliveryStore(path=_temp_ledger_path(), legacy_path=None),
    )
    monkeypatch.setattr(run_trump_monitor, "read_json", lambda *a, **k: {})
    monkeypatch.setattr(run_trump_monitor, "send_telegram", lambda *a, **k: True)
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
    assert health["source_completeness_verified"] is False


def test_long_post_is_split_without_truncation_or_early_seen():
    text = "政策內容 " * 1200
    post = _post("long-1", text)
    chunks = run_trump_monitor.build_delivery_chunks([post])

    assert len(chunks) > 1
    delivered = "".join(chunk["message"] for chunk in chunks)
    assert delivered.count("政策內容") == text.count("政策內容")
    assert all(chunk["mark_posts"] == [] for chunk in chunks[:-1])
    assert chunks[-1]["mark_posts"] == [post]


def test_failed_middle_of_long_post_does_not_mark_seen(monkeypatch):
    post = _post("long-fail", "內容 " * 3000)
    ledger_path = _temp_ledger_path()
    state = {"sent": [], "writes": {}, "ledger_path": ledger_path}
    monkeypatch.setattr(
        run_trump_monitor,
        "fetch_recent_posts_with_health",
        lambda: _healthy_result([post]),
    )
    monkeypatch.setattr(
        run_trump_monitor,
        "TrumpDeliveryStore",
        lambda: TrumpDeliveryStore(path=ledger_path, legacy_path=None),
    )
    monkeypatch.setattr(run_trump_monitor, "archive_posts", lambda value, **k: len(value))
    monkeypatch.setattr(run_trump_monitor, "get_default_translator", lambda: None)
    calls = {"count": 0}

    def _detailed(message, **kwargs):
        calls["count"] += 1
        state["sent"].append((message, kwargs))
        # First fragment reaches recipients, a later fragment definitively
        # fails: some content already went out, so the post is a partial
        # (ambiguous) outbound — quarantined, never marked sent, never retried.
        outcome = "sent" if calls["count"] == 1 else "failed"
        return {"outcome": outcome, "delivered": 1, "total": 1}

    monkeypatch.setattr(run_trump_monitor, "send_telegram_detailed", _detailed)
    monkeypatch.setattr(run_trump_monitor, "read_json", lambda *a, **k: {})
    monkeypatch.setattr(run_trump_monitor, "write_json", lambda *a, **k: True)

    assert run_trump_monitor.main() == 1
    assert _delivered_ids(state) == []
    assert _ledger_state(state, "long-fail") == "ambiguous"
