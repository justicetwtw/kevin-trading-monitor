"""股癌 RSS 抓取 + 解析 + dedup 過濾。

httpx 取原始 XML(follow_redirects=True)→ feedparser 解析。
網路失敗一律 try/except 回 [](紅線 §4:單點失敗不阻塞)。
filter_unseen 為純函式(無 IO),含首次執行 bootstrap 保護(§6)。
"""

from __future__ import annotations

import httpx
import feedparser
from loguru import logger

# 抓 feed 的 timeout / UA(比照 trump_truth.py 慣例)
_FEED_TIMEOUT_SEC = 20.0
_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _parse_duration(raw) -> int | None:
    """把 itunes:duration 轉成秒數。

    支援 "HH:MM:SS" / "MM:SS" / 純秒數字串;解析不了回 None。
    """
    if raw is None:
        return None
    raw = str(raw).strip()
    if not raw:
        return None
    try:
        if ":" in raw:
            parts = [int(p) for p in raw.split(":")]
            sec = 0
            for p in parts:
                sec = sec * 60 + p
            return sec
        return int(float(raw))
    except (ValueError, TypeError):
        return None


def _extract_audio_url(entry) -> str:
    """從 enclosures 取音檔 URL(優先 type 以 audio 開頭的)。"""
    encs = entry.get("enclosures") or []
    # 優先明確標 audio/* 的
    for enc in encs:
        if str(enc.get("type", "")).lower().startswith("audio"):
            href = enc.get("href") or enc.get("url") or ""
            if href:
                return href
    # 退而求其次:第一個有 href 的 enclosure
    for enc in encs:
        href = enc.get("href") or enc.get("url") or ""
        if href:
            return href
    return ""


def fetch_feed(rss_url: str) -> list[dict]:
    """抓 + 解析 RSS,回傳 [{guid, title, published, audio_url, duration_sec}, ...]。

    newest first(feed 通常已是新到舊,仍保留原序)。
    網路 / 解析失敗 → log warning + 回 [](不拋例外,不阻塞 pipeline)。
    """
    try:
        with httpx.Client(timeout=_FEED_TIMEOUT_SEC, follow_redirects=True) as client:
            resp = client.get(rss_url, headers=_HEADERS)
            resp.raise_for_status()
            xml = resp.text
    except Exception as e:
        logger.warning(f"Gooaye feed fetch failed: {e}")
        return []

    try:
        parsed = feedparser.parse(xml)
    except Exception as e:
        logger.warning(f"Gooaye feed parse failed: {e}")
        return []

    episodes: list[dict] = []
    for entry in parsed.entries:
        guid = entry.get("id") or entry.get("guid") or entry.get("link") or ""
        audio_url = _extract_audio_url(entry)
        if not guid or not audio_url:
            # 沒 guid 或沒音檔的 item 無法處理 / dedup,跳過
            continue
        episodes.append(
            {
                "guid": str(guid),
                "title": (entry.get("title") or "").strip(),
                "published": entry.get("published") or entry.get("updated") or "",
                "audio_url": audio_url,
                "duration_sec": _parse_duration(entry.get("itunes_duration")),
            }
        )

    logger.info(f"Gooaye feed: parsed {len(episodes)} episodes")
    return episodes


def filter_unseen(
    episodes: list[dict],
    seen_guids: set,
    max_n: int,
    is_bootstrap: bool,
) -> tuple[list[dict], set]:
    """過濾出要處理的集 + 要『立即標 seen(不處理)』的 guid。純函式。

    Returns:
      (to_process, to_mark_now)
        to_process : 真的要跑 pipeline 的集(成功後才由 pipeline 標 seen)
        to_mark_now: 不處理但要馬上寫進 seen 的 guid(bootstrap 的 back catalog)

    規則:
      - bootstrap(seen 空,§6):只處理最新 max_n 集(實務上 BOOTSTRAP_PROCESS_COUNT=1),
        其餘整個 back catalog 全部 guid 立即標 seen → 永不轉錄。
      - 一般:取尚未 seen 的集,newest first,上限 max_n;to_mark_now 為空
        (超過 max_n 的新集留待後續 run 處理,不立即標 seen)。
    """
    seen_guids = set(seen_guids or set())
    unseen = [ep for ep in episodes if ep.get("guid") not in seen_guids]

    if is_bootstrap:
        to_process = unseen[:max_n]
        processed_guids = {ep["guid"] for ep in to_process}
        # back catalog:本次 feed 內、不處理的全部 guid 立即標 seen
        to_mark_now = {
            ep["guid"] for ep in episodes if ep["guid"] not in processed_guids
        }
        logger.warning(
            f"Gooaye bootstrap: processing {len(to_process)} newest, "
            f"marking {len(to_mark_now)} back-catalog episodes as seen"
        )
        return to_process, to_mark_now

    to_process = unseen[:max_n]
    if len(unseen) > max_n:
        logger.info(
            f"Gooaye: {len(unseen)} unseen, capped to {max_n} this run "
            f"(rest picked up next run)"
        )
    return to_process, set()
