"""Live, content-free health probe for the Trump Truth Social source.

This is intentionally separate from the scheduled monitor. It does not archive,
mark seen or send Telegram. CI can prove whether a GitHub-hosted runner can
currently reach a fresh source without exposing post text.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from src.data.trump_truth import fetch_recent_posts_with_health

OUTPUT = Path("trump_source_probe.json")


def main() -> int:
    result = fetch_recent_posts_with_health()
    safe = {
        "status": result.get("status"),
        "source": result.get("source"),
        "latest_post_at": result.get("latest_post_at"),
        "source_raw_count": result.get("raw_count"),
        "source_returned_count": result.get("returned_count"),
        "source_limit": result.get("source_limit"),
        "attempts": result.get("attempts", []),
        "error": result.get("error"),
        "content_included": False,
    }
    OUTPUT.write_text(json.dumps(safe, indent=2), encoding="utf-8")
    print(json.dumps(safe, indent=2))
    return 0 if safe["status"] == "healthy" else 1


if __name__ == "__main__":
    sys.exit(main())
