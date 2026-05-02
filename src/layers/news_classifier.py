"""Layer 0+.2 - RSS 新聞分類

只回「最近 N 分鐘掃到並過濾的 items」,不加減分,不做 valid_until。
60 分鐘有效期過濾邏輯由 Batch 7 signals 層處理。
"""

from datetime import datetime, timezone

from loguru import logger

from src.data.rss_feeds import fetch_all_feeds, filter_by_keywords
from src.storage.state_manager import write_json


def scan_recent_news(lookback_minutes: int = 15) -> list:
    """抓最近 RSS 並依關鍵字過濾。失敗回 []。"""
    try:
        items = fetch_all_feeds(lookback_minutes) or []
        filtered = filter_by_keywords(items) or []
        try:
            write_json("layer_news_classifier_state.json", {
                "items": filtered,
                "lookback_minutes": lookback_minutes,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as we:
            logger.warning(f"news_classifier state write failed (non-fatal): {we}")
        return filtered
    except Exception as e:
        logger.warning(f"scan_recent_news failed (cold-start fallback): {e}")
        return []
