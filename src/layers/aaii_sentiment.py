"""Layer 0.7 - AAII 情緒(週四更新)

抓 https://www.aaii.com/sentimentsurvey/sent_results,regex 抓 Bullish/Neutral/Bearish 百分比。
spread = bull - bear。spread > 30 → -5(極端樂觀,反向),spread < -20 → +5(極端悲觀,反向)。
clip 到 LAYER0_SUBMODIFIER_RANGES["aaii_sentiment"]=(-5, 5)。
"""

import re
from datetime import datetime, timezone

import httpx
from loguru import logger
from selectolax.parser import HTMLParser
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_not_exception_type

from src.config.thresholds import LAYER0_SUBMODIFIER_RANGES
from src.storage.state_manager import write_json


_RANGE_KEY = "aaii_sentiment"
HEADERS = {"User-Agent": "Mozilla/5.0"}
AAII_URL = "https://www.aaii.com/sentimentsurvey/sent_results"


def _clip(modifier: int) -> int:
    lo, hi = LAYER0_SUBMODIFIER_RANGES[_RANGE_KEY]
    return int(max(lo, min(hi, modifier)))


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_not_exception_type((ValueError, RuntimeError)),
    reraise=True,
)
def _fetch_html() -> str:
    with httpx.Client(timeout=20.0, headers=HEADERS, follow_redirects=True) as c:
        r = c.get(AAII_URL)
        r.raise_for_status()
        return r.text


def fetch_aaii_latest() -> dict:
    """從 AAII 網站抓最新一週情緒調查。失敗回 {}。"""
    try:
        html = _fetch_html()
        tree = HTMLParser(html)
        text = tree.text()
        m_bull = re.search(r"Bullish[\s\S]{0,80}?(\d+\.\d+)%", text)
        m_neu = re.search(r"Neutral[\s\S]{0,80}?(\d+\.\d+)%", text)
        m_bear = re.search(r"Bearish[\s\S]{0,80}?(\d+\.\d+)%", text)

        if m_bull and m_bear:
            bull = float(m_bull.group(1))
            bear = float(m_bear.group(1))
            neu = float(m_neu.group(1)) if m_neu else (100 - bull - bear)
            return {
                "bullish": bull,
                "bearish": bear,
                "neutral": neu,
                "spread": bull - bear,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
        return {}
    except Exception as e:
        logger.warning(f"fetch_aaii_latest failed: {e}")
        return {}


def classify_aaii() -> dict:
    try:
        data = fetch_aaii_latest()
        if not data:
            result = {
                "data": {},
                "modifier": 0,
                "regime": "cold_start",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
        else:
            spread = data.get("spread", 0)
            min_mod, max_mod = LAYER0_SUBMODIFIER_RANGES[_RANGE_KEY]
            if spread > 30:
                modifier = min_mod  # -5
            elif spread < -20:
                modifier = max_mod  # +5
            else:
                modifier = 0
            result = {
                "data": data,
                "modifier": _clip(modifier),
                "regime": (
                    "extreme_bullish" if spread > 30 else
                    "extreme_bearish" if spread < -20 else "neutral"
                ),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                write_json("aaii_history.json", data)
            except Exception as we:
                logger.warning(f"aaii_history write failed (non-fatal): {we}")

        try:
            write_json("layer_aaii_sentiment_state.json", result)
        except Exception as we:
            logger.warning(f"aaii state write failed (non-fatal): {we}")
        return result
    except Exception as e:
        logger.warning(f"classify_aaii failed (cold-start fallback): {e}")
        return {
            "data": {},
            "modifier": 0,
            "regime": "cold_start",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
        }
