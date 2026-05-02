"""RSS 新聞抓取 - Reuters / AP / Fed

寫入:data_store/rss_seen.json(去重,避免重複推播)
過濾:src.config.rss_sources.NEWS_FILTER_KEYWORDS 三類 macro / geopolitical / tech
"""

from datetime import datetime, timedelta
from typing import Optional

import feedparser
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config.rss_sources import NEWS_FILTER_KEYWORDS, RSS_SOURCES
from src.config.settings import TIMEZONE_US_MARKET
from src.storage.state_manager import read_json, write_json

SEEN_FILE = "rss_seen.json"
MAX_SEEN = 5000


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_feed(url: str, lookback_minutes: int = 60) -> list:
    """抓單個 RSS,只回傳指定時間內的 entries。"""
    try:
        feed = feedparser.parse(url)
        # feedparser 有自己的容錯,bozo=1 通常仍可用,但我們再做一層檢查
        if not getattr(feed, "entries", None):
            return []
        cutoff = datetime.utcnow() - timedelta(minutes=lookback_minutes)
        items = []
        for entry in feed.entries:
            pub = entry.get("published_parsed") or entry.get("updated_parsed")
            if pub:
                try:
                    pub_dt = datetime(*pub[:6])
                    if pub_dt < cutoff:
                        continue
                except (TypeError, ValueError):
                    pass  # 時間解析失敗 → 仍納入,讓下游決定
            items.append({
                "id": entry.get("id") or entry.get("link", ""),
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "summary": entry.get("summary", ""),
                "published": entry.get("published", ""),
                "source_url": url,
            })
        return items
    except Exception as e:
        logger.error(f"fetch_feed({url}) failed: {e}")
        return []


def fetch_all_feeds(lookback_minutes: int = 15) -> list:
    """全 RSS 來源抓取。任一 feed 失敗 → 該 feed 回 [],其他繼續。"""
    all_items = []
    for name, url in RSS_SOURCES.items():
        try:
            items = fetch_feed(url, lookback_minutes)
        except Exception as e:
            logger.warning(f"feed {name} retries exhausted: {e}")
            items = []
        for it in items:
            it["feed_name"] = name
        all_items.extend(items)
    return all_items


def _categorize(matched_kws: list) -> str:
    """matched 已是純 keywords list,從 NEWS_FILTER_KEYWORDS 反查分類"""
    matched_set = set(kw.lower() for kw in matched_kws)
    for cat, kws in NEWS_FILTER_KEYWORDS.items():
        cat_set = set(kw.lower() for kw in kws)
        if matched_set & cat_set:
            return cat
    return "other"


def filter_by_keywords(items: list) -> list:
    """關鍵字過濾(macro / geopolitical / tech)"""
    flat_keywords = []
    for cat_kws in NEWS_FILTER_KEYWORDS.values():
        flat_keywords.extend(kw.lower() for kw in cat_kws)

    filtered = []
    for it in items:
        text = (it.get("title", "") + " " + it.get("summary", "")).lower()
        matched_kws = [kw for kw in flat_keywords if kw in text]
        if matched_kws:
            it["matched_keywords"] = matched_kws
            it["category"] = _categorize(matched_kws)
            filtered.append(it)
    return filtered


def filter_new_items(items: list) -> list:
    """去重:用 link 當 key,寫 data_store/rss_seen.json,避免重複推播"""
    seen = read_json(SEEN_FILE, default={})
    if not isinstance(seen, dict):
        seen = {}

    now_iso = datetime.now(TIMEZONE_US_MARKET).isoformat()
    new_items = []
    for it in items:
        key = it.get("id") or it.get("link", "")
        if not key or key in seen:
            continue
        new_items.append(it)
        seen[key] = {"seen_at": now_iso, "title": it.get("title", "")[:200]}

    # 限長
    if len(seen) > MAX_SEEN:
        sorted_items = sorted(seen.items(), key=lambda x: x[1].get("seen_at", ""))
        seen = dict(sorted_items[-MAX_SEEN:])

    write_json(SEEN_FILE, seen)
    return new_items


def fetch_filter_dedup(lookback_minutes: int = 15) -> list:
    """完整流程:抓取 → 關鍵字過濾 → 去重。供 runner 用。"""
    items = fetch_all_feeds(lookback_minutes)
    filtered = filter_by_keywords(items)
    return filter_new_items(filtered)
