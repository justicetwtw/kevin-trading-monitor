"""泡沫偵測指標 - currentmarketvaluation.com / multpl.com / slickcharts

任何子指標失敗 = 該欄位 None;
get_bubble_snapshot() 會在所有指標都 None 時回 {"score": None, "indicators": {}}
讓 layer 端視為 neutral,不阻塞流程。
"""

import re
from datetime import datetime
from typing import Optional

import httpx
from loguru import logger
from selectolax.parser import HTMLParser
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config.settings import TIMEZONE_US_MARKET

HEADERS = {"User-Agent": "Mozilla/5.0"}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_buffett_indicator() -> Optional[float]:
    """Buffett Indicator(US Total Market Cap / GDP),來源 currentmarketvaluation.com"""
    try:
        url = "https://www.currentmarketvaluation.com/models/buffett-indicator.php"
        with httpx.Client(timeout=15.0, headers=HEADERS, follow_redirects=True) as c:
            r = c.get(url)
            r.raise_for_status()
            tree = HTMLParser(r.text)
            text = tree.text()
            m = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
            if m:
                return float(m.group(1)) / 100
        return None
    except Exception as e:
        logger.error(f"fetch_buffett_indicator failed: {e}")
        return None


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_shiller_cape() -> Optional[float]:
    """Shiller CAPE(multpl.com)"""
    try:
        url = "https://www.multpl.com/shiller-pe"
        with httpx.Client(timeout=15.0, headers=HEADERS, follow_redirects=True) as c:
            r = c.get(url)
            r.raise_for_status()
            tree = HTMLParser(r.text)
            node = tree.css_first("#current")
            if node:
                m = re.search(r"(\d+\.\d+)", node.text())
                if m:
                    return float(m.group(1))
        return None
    except Exception as e:
        logger.error(f"fetch_shiller_cape failed: {e}")
        return None


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_sp500_top10_concentration() -> Optional[float]:
    """SPX Top 10 集中度(slickcharts)"""
    try:
        url = "https://www.slickcharts.com/sp500"
        with httpx.Client(timeout=15.0, headers=HEADERS, follow_redirects=True) as c:
            r = c.get(url)
            r.raise_for_status()
            tree = HTMLParser(r.text)
            rows = tree.css("table tbody tr")[:10]
            total = 0.0
            for row in rows:
                cells = row.css("td")
                if len(cells) >= 4:
                    try:
                        weight = float(cells[3].text(strip=True).replace("%", ""))
                        total += weight
                    except ValueError:
                        continue
            return total / 100 if total else None
    except Exception as e:
        logger.error(f"fetch_sp500_top10_concentration failed: {e}")
        return None


def fetch_margin_debt_yoy() -> Optional[float]:
    """Margin Debt YoY(FINRA / advisorperspectives)
    更新月度,Phase 2 暫回 None;Phase 3 補完(可走 advisorperspectives CSV)。
    """
    return None


def get_bubble_snapshot() -> dict:
    """完整泡沫快照。
    任何子指標失敗 → 該欄位 None;
    全部 None → indicators 內所有值都 None,score 也 None,
    layer 端應視為 neutral 不阻塞。
    """
    indicators = {
        "buffett_indicator": None,
        "shiller_cape": None,
        "sp500_top10_concentration": None,
        "margin_debt_yoy": None,
    }
    fetchers = {
        "buffett_indicator": fetch_buffett_indicator,
        "shiller_cape": fetch_shiller_cape,
        "sp500_top10_concentration": fetch_sp500_top10_concentration,
        "margin_debt_yoy": fetch_margin_debt_yoy,
    }
    for key, fn in fetchers.items():
        try:
            indicators[key] = fn()
        except Exception as e:
            logger.warning(f"bubble {key} retries exhausted: {e}")
            indicators[key] = None

    # 全部 None → score 也 None;否則由 layer 端去 weight
    available = [v for v in indicators.values() if v is not None]
    score = None  # Phase 2 不在 data 層算 score,留給 layers/bubble.py 加權

    return {
        "score": score,
        "indicators": indicators,
        "n_available": len(available),
        "fetched_at": datetime.now(TIMEZONE_US_MARKET).isoformat(),
    }
