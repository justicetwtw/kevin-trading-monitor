"""Layer 0+.1 - Trump Truth Social 三級分類

只產生 tag(post_id / tier / matched_keywords / events / created_at / scan_time),不加減分。
60 分鐘有效期過濾邏輯由 Batch 7 signals 層處理(scorer 自己看 created_at + 60min)。
"""

from datetime import datetime, timezone

from loguru import logger

from src.config.keywords import classify_post, get_matched_keywords
from src.config.position_mapping import map_event_to_positions
from src.data.trump_truth import fetch_recent_posts, filter_new_posts, extract_text
from src.storage.state_manager import write_json


def scan_and_classify() -> list:
    """抓新貼文 + 分類 + 映射部位。失敗回 []。"""
    try:
        posts = fetch_recent_posts() or []
        new_posts = filter_new_posts(posts) or []

        classified = []
        for p in new_posts:
            try:
                text = extract_text(p)
                if not text:
                    continue
                tier = classify_post(text)
                if tier == "tier3":
                    continue  # 入庫不推

                matched = get_matched_keywords(text)
                events = map_event_to_positions(matched)

                classified.append({
                    "post_id": str(p.get("id", "")),
                    "tier": tier,
                    "text": text[:500],
                    "created_at": p.get("created_at", ""),
                    "matched_keywords": matched,
                    "events": events,
                    "scan_time": datetime.now(timezone.utc).isoformat(),
                })
            except Exception as inner_e:
                logger.warning(f"trump_classifier per-post failed (skip): {inner_e}")
                continue

        try:
            write_json("layer_trump_classifier_state.json", {
                "classified": classified,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as we:
            logger.warning(f"trump_classifier state write failed (non-fatal): {we}")
        return classified
    except Exception as e:
        logger.warning(f"scan_and_classify failed (cold-start fallback): {e}")
        return []
