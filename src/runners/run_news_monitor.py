"""RSS 新聞監控 (10 分鐘 cron)。

⚠ Section 12.2 spec 已廢棄(fetch_all_rss / classify_news 都不存在)。
真實實作:fetch_all_feeds(15min) → filter_by_keywords → cold_start 24h → filter_new_items → push。

偏離決策:news_classifier 沒有 tier 邏輯,所有 matched 預設 tier=2 yellow。
冷啟動保護 defense in depth(模組層 lookback=15min 已自帶緩衝)。
"""

from datetime import datetime, timezone

from dateutil.parser import parse as date_parse
from loguru import logger

from src.alerts.alert_formatter import format_news_alert
from src.alerts.alert_router import route_alert
from src.data.rss_feeds import (
    SEEN_FILE,
    fetch_all_feeds,
    filter_by_keywords,
    filter_new_items,
)
from src.runners._cold_start import filter_with_cold_start_protection
from src.storage.state_manager import read_json


def _get_item_ts(it: dict):
    s = it.get("published")
    if not s:
        return None
    try:
        return date_parse(s)
    except (ValueError, TypeError):
        return None


def main() -> None:
    logger.info("=== run_news_monitor start ===")
    try:
        seen_before = read_json(SEEN_FILE, default={})
        items = fetch_all_feeds(lookback_minutes=15) or []
        filtered = filter_by_keywords(items) or []
        if not filtered:
            logger.info("=== run_news_monitor done (0 matched) ===")
            return

        to_process, to_mark = filter_with_cold_start_protection(
            items=filtered,
            seen_set=seen_before,
            get_created_at=_get_item_ts,
            cold_start_window_hours=24,
        )

        new_items = filter_new_items(to_process + to_mark)
        process_keys = {it.get("id") or it.get("link") for it in to_process}

        pushed = 0
        for it in new_items:
            try:
                key = it.get("id") or it.get("link")
                if key not in process_keys:
                    continue
                alert = {
                    "source": it.get("feed_name", "RSS"),
                    "tier": 2,
                    "title": it.get("title", ""),
                    "url": it.get("link", ""),
                    "alert_level": "yellow",
                    "kind": "news",
                    "matched_keywords": it.get("matched_keywords", []),
                    "category": it.get("category", "other"),
                    "scan_time": datetime.now(timezone.utc).isoformat(),
                }
                alert["message"] = format_news_alert(alert)
                if route_alert(alert):
                    pushed += 1
            except Exception as e:
                logger.error(f"News per-item failed (skip): {e}")

        logger.info(f"=== run_news_monitor done ({pushed} pushed) ===")
    except Exception as e:
        logger.error(f"run_news_monitor crashed: {e}")


if __name__ == "__main__":
    main()
