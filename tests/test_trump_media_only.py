"""Media-only Trump activities must not be dropped for lacking text."""

from datetime import datetime, timezone

from src.data import trump_truth
from src.runners import run_trump_monitor


def test_media_only_status_is_usable_and_deliverable(monkeypatch):
    raw = {
        "id": "media-only-1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "content": "",
        "url": "https://truthsocial.com/@realDonaldTrump/media-only-1",
        "media_attachments": [{"id": "image-1"}],
    }
    monkeypatch.setattr(trump_truth, "fetch_from_truth_api", lambda: [raw])
    monkeypatch.setattr(
        trump_truth,
        "fetch_from_cnn_mirror",
        lambda: (_ for _ in ()).throw(
            AssertionError("official source is fresh")
        ),
    )

    result = trump_truth.fetch_recent_posts_with_health()

    assert result["status"] == "healthy"
    assert len(result["posts"]) == 1
    post = result["posts"][0]
    assert post["id"] == "media-only-1"
    assert post["text"] == ""
    assert post["media_count"] == 1

    chunks = run_trump_monitor.build_delivery_chunks([post])
    assert "[無文字內容]" in chunks[0]["message"]
    assert "媒體附件 1" in chunks[0]["message"]
    assert chunks[0]["mark_posts"] == [post]
