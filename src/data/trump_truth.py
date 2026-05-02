"""Trump Truth Social 抓取(R2 風險:來源不穩,雙源都失敗回空 list 不阻塞)

主來源:CNN JSON 鏡像(穩定且不需 auth)
備援:Truth Social 公開 API
寫入:data_store/trump_seen_posts.json(去重 + 限長 2000)

分類:呼叫 src.config.keywords.classify_post() 把貼文分 tier1/tier2/tier3
"""

from datetime import datetime
from typing import Optional

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config.keywords import classify_post, get_matched_keywords
from src.config.rss_sources import TRUMP_TRUTH_SOURCES
from src.config.settings import TIMEZONE_US_MARKET
from src.storage.state_manager import read_json, write_json

SEEN_POSTS_FILE = "trump_seen_posts.json"
MAX_SEEN = 2000


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=8))
def fetch_from_cnn_mirror() -> list:
    """主來源:CNN 鏡像"""
    url = TRUMP_TRUTH_SOURCES["primary_cnn_mirror"]
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            r = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list):
                return data
            return data.get("posts", []) if isinstance(data, dict) else []
    except Exception as e:
        logger.warning(f"CNN mirror failed: {e}")
        return []


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=8))
def fetch_from_truth_api() -> list:
    """備援:Truth Social 公開 API"""
    url = TRUMP_TRUTH_SOURCES["fallback_truth_api"]
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            r = client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            )
            r.raise_for_status()
            j = r.json()
            return j if isinstance(j, list) else []
    except Exception as e:
        logger.warning(f"Truth API failed: {e}")
        return []


def fetch_recent_posts() -> list:
    """主備雙源。雙源都失敗 → 回 [],log warning,不阻塞下游 runner。"""
    try:
        posts = fetch_from_cnn_mirror()
    except Exception as e:
        logger.warning(f"CNN mirror retries exhausted: {e}")
        posts = []
    if not posts:
        logger.info("CNN mirror empty, trying Truth API")
        try:
            posts = fetch_from_truth_api()
        except Exception as e:
            logger.warning(f"Truth API retries exhausted: {e}")
            posts = []
    if not posts:
        logger.warning("Trump posts: BOTH sources failed/empty (non-blocking)")
    return posts


def filter_new_posts(posts: list) -> list:
    """過濾掉已處理的貼文。seen 字典 limit 2000 條,超過丟最舊。"""
    seen = read_json(SEEN_POSTS_FILE, default={})
    if not isinstance(seen, dict):
        seen = {}

    new_posts = []
    now_iso = datetime.now(TIMEZONE_US_MARKET).isoformat()
    for p in posts:
        pid = str(p.get("id") or p.get("post_id") or "")
        if not pid or pid in seen:
            continue
        new_posts.append(p)
        seen[pid] = {
            "seen_at": now_iso,
            "created_at": p.get("created_at", ""),
        }

    if len(seen) > MAX_SEEN:
        sorted_items = sorted(seen.items(), key=lambda x: x[1].get("seen_at", ""))
        seen = dict(sorted_items[-MAX_SEEN:])

    write_json(SEEN_POSTS_FILE, seen)
    return new_posts


def extract_text(post: dict) -> str:
    """從不同來源結構中拉出純文字內容。"""
    if "content" in post:
        # Truth Social API 的 content 是 HTML
        try:
            from selectolax.parser import HTMLParser
            return HTMLParser(post["content"]).text(strip=True)
        except Exception:
            return post["content"]
    return post.get("text", "") or post.get("body", "")


def classify_and_enrich(post: dict) -> dict:
    """把貼文加上 tier 分類 + matched_keywords,供下游 layers/trump_classifier.py 用"""
    text = extract_text(post)
    tier = classify_post(text)
    matched = get_matched_keywords(text)
    return {
        "post": post,
        "text": text,
        "tier": tier,
        "matched_keywords": matched,
        "classified_at": datetime.now(TIMEZONE_US_MARKET).isoformat(),
    }


def fetch_and_classify_new() -> list:
    """完整流程:抓取 → 去重 → 分類。供 runner 直接呼叫。"""
    posts = fetch_recent_posts()
    new_posts = filter_new_posts(posts)
    return [classify_and_enrich(p) for p in new_posts]
