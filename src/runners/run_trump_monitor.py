"""Trump Truth Social 監控 (5 分鐘 cron)。

⚠ Section 12.1 spec 已廢棄(spec 引用 fetch_latest_trump_posts / classify_trump_post 都不存在)。
真實實作:fetch_recent_posts → cold_start 24h 過濾 → filter_new_posts(寫 seen) → classify_post → push。

冷啟動保護:CNN 鏡像有 32k 則歷史貼文,首跑用 _cold_start helper 把 24h 外貼文標 seen 不推。
"""

from datetime import datetime, timezone

from dateutil.parser import isoparse
from loguru import logger

from src.alerts.alert_formatter import format_news_alert
from src.alerts.alert_router import route_alert
from src.config.keywords import classify_post, get_matched_keywords
from src.data.trump_truth import (
    SEEN_POSTS_FILE,
    extract_text,
    fetch_recent_posts,
    filter_new_posts,
)
from src.runners._cold_start import filter_with_cold_start_protection
from src.storage.state_manager import read_json


def _get_post_ts(p: dict):
    s = p.get("created_at")
    if not s:
        return None
    try:
        return isoparse(s)
    except (ValueError, TypeError):
        return None


def main() -> None:
    logger.info("=== run_trump_monitor start ===")
    try:
        seen_before = read_json(SEEN_POSTS_FILE, default={})
        posts = fetch_recent_posts() or []
        if not posts:
            logger.warning("Trump: no posts fetched")
            logger.info("=== run_trump_monitor done (0 pushed) ===")
            return

        to_process, to_mark = filter_with_cold_start_protection(
            items=posts,
            seen_set=seen_before,
            get_created_at=_get_post_ts,
            cold_start_window_hours=24,
        )

        # filter_new_posts 會把 input 全部寫進 seen,回傳「先前未見過」的
        new_posts = filter_new_posts(to_process + to_mark)
        process_ids = {
            str(p.get("id") or p.get("post_id") or "") for p in to_process
        }

        pushed = 0
        for p in new_posts:
            try:
                pid = str(p.get("id") or p.get("post_id") or "")
                if pid not in process_ids:
                    continue
                text = extract_text(p)
                if not text:
                    continue
                tier_str = classify_post(text)
                if tier_str not in ("tier1", "tier2"):
                    continue
                tier_int = 1 if tier_str == "tier1" else 2
                alert = {
                    "source": "Trump",
                    "tier": tier_int,
                    "title": text[:200],
                    "url": p.get("url", ""),
                    "alert_level": "green" if tier_int == 1 else "yellow",
                    "kind": "news",
                    "matched_keywords": get_matched_keywords(text),
                    "scan_time": datetime.now(timezone.utc).isoformat(),
                }
                alert["message"] = format_news_alert(alert)
                if route_alert(alert):
                    pushed += 1
            except Exception as e:
                logger.error(f"Trump per-post failed (skip): {e}")

        logger.info(f"=== run_trump_monitor done ({pushed} pushed) ===")
    except Exception as e:
        logger.error(f"run_trump_monitor crashed: {e}")


if __name__ == "__main__":
    main()
