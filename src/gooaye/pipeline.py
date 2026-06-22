"""股癌 digest pipeline:feed → 下載 → 轉錄 → 摘要 → email → 標記 seen。

紅線:
- §6 bootstrap:首跑(seen 空)只處理最新 1 集,其餘 back catalog 全標 seen。
- §5/§4:每集獨立 try/except,單集失敗只跳過那一集,不炸整個 run。
- dedup gate 所有 Gemini 呼叫:已 seen 的 guid 永不重跑(紅線 §1)。
- seen 狀態用 state_manager(read_json/write_json),比照 trump_seen 慣例。
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime

import httpx
from loguru import logger

from src.config import gooaye_config
from src.config.settings import TIMEZONE_USER
from src.gooaye import emailer
from src.gooaye.feed import fetch_feed, filter_unseen
from src.gooaye.summarizer import summarize
from src.gooaye.transcriber import transcribe
from src.storage.state_manager import read_json, write_json

_DOWNLOAD_TIMEOUT_SEC = 120.0
_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _load_seen() -> dict:
    """載入 seen 狀態(dict: guid → {seen_at, title}),比照 rss_seen.json 結構。"""
    seen = read_json(gooaye_config.GOOAYE_SEEN_FILE, default={})
    return seen if isinstance(seen, dict) else {}


def _mark_seen(seen: dict, guid: str, title: str) -> None:
    seen[guid] = {
        "seen_at": datetime.now(TIMEZONE_USER).isoformat(),
        "title": title,
    }


def _download_mp3(url: str) -> str | None:
    """串流下載 MP3 到暫存檔,回傳路徑;失敗回 None(暫存檔會清掉)。"""
    fd, path = tempfile.mkstemp(suffix=".mp3", prefix="gooaye_")
    os.close(fd)
    try:
        with httpx.stream(
            "GET",
            url,
            follow_redirects=True,
            timeout=_DOWNLOAD_TIMEOUT_SEC,
            headers=_HEADERS,
        ) as resp:
            resp.raise_for_status()
            with open(path, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=1 << 16):
                    f.write(chunk)
        size = os.path.getsize(path)
        if size <= 0:
            logger.error("下載的 MP3 為 0 bytes")
            _cleanup(path)
            return None
        logger.info(f"Gooaye MP3 downloaded: {size/1_048_576:.1f} MB")
        return path
    except Exception as e:
        logger.error(f"Gooaye MP3 download failed: {e}")
        _cleanup(path)
        return None


def _cleanup(path: str | None) -> None:
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError as e:
            logger.warning(f"暫存檔清除失敗: {e}")


def _process_episode(ep: dict, seen: dict) -> bool:
    """處理單集:下載→轉錄→摘要→寄信。全部成功才標 seen + 回 True。

    任一步失敗 → log + 回 False,不標 seen(下次 run 會重試該集)。
    """
    guid = ep.get("guid", "")
    title = ep.get("title", "(無標題)")
    logger.info(f"Gooaye 處理集數: {title}")

    mp3_path = None
    try:
        mp3_path = _download_mp3(ep.get("audio_url", ""))
        if not mp3_path:
            return False

        transcript = transcribe(mp3_path)
        if not transcript:
            logger.error(f"轉錄失敗,跳過: {title}")
            return False

        summary = summarize(transcript)
        if not summary:
            logger.error(f"摘要失敗,跳過: {title}")
            return False

        sent = emailer.send_digest(
            title=title,
            summary_md=summary,
            transcript_md=transcript,
            published=ep.get("published", ""),
        )
        if not sent:
            logger.error(f"寄信失敗,跳過(不標 seen,下次重試): {title}")
            return False

        # 全程成功才標 seen
        _mark_seen(seen, guid, title)
        write_json(gooaye_config.GOOAYE_SEEN_FILE, seen)
        logger.info(f"Gooaye 集數完成並標記 seen: {title}")
        return True
    except Exception as e:
        logger.error(f"Gooaye 集數處理例外(跳過): {title} — {e}")
        return False
    finally:
        _cleanup(mp3_path)


def run() -> int:
    """跑完整 pipeline。回傳 0(成功 / no-op)/ 1(有集處理失敗或頂層例外)。"""
    logger.info("=== run_gooaye_digest start ===")
    try:
        seen = _load_seen()
        is_bootstrap = len(seen) == 0
        seen_guids = set(seen.keys())

        episodes = fetch_feed(gooaye_config.GOOAYE_RSS_URL)
        if not episodes:
            logger.warning("Gooaye: feed 無集數或抓取失敗(no-op)")
            logger.info("=== run_gooaye_digest done (0 processed) ===")
            return 0

        max_n = (
            gooaye_config.BOOTSTRAP_PROCESS_COUNT
            if is_bootstrap
            else gooaye_config.MAX_EPISODES_PER_RUN
        )
        to_process, to_mark_now = filter_unseen(
            episodes, seen_guids, max_n, is_bootstrap
        )

        # bootstrap:back catalog 先立即標 seen 並落地,避免後續崩潰又重灌(紅線 §6)
        if to_mark_now:
            ep_by_guid = {ep["guid"]: ep for ep in episodes}
            for guid in to_mark_now:
                _mark_seen(seen, guid, ep_by_guid.get(guid, {}).get("title", ""))
            write_json(gooaye_config.GOOAYE_SEEN_FILE, seen)
            logger.info(f"Gooaye: 已標記 {len(to_mark_now)} 集 back catalog 為 seen")

        if not to_process:
            logger.info("Gooaye: 無新集要處理(dedup no-op)")
            logger.info("=== run_gooaye_digest done (0 processed) ===")
            return 0

        failures = 0
        succeeded = 0
        for ep in to_process:
            if _process_episode(ep, seen):
                succeeded += 1
            else:
                failures += 1

        logger.info(
            f"=== run_gooaye_digest done ({succeeded} ok / {failures} failed) ==="
        )
        return 0 if failures == 0 else 1
    except Exception as e:
        logger.error(f"run_gooaye_digest crashed: {e}")
        return 1
