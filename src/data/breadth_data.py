"""市場廣度 - StockCharts scraping(高風險 R3)

來源網站結構不穩,雙 parser 防線:
1. selectolax(主)— 速度快、CSS selector 涵蓋 .last-quote / .price / span.quote
2. BeautifulSoup(備)— selectolax 抓不到任何節點時用 BS4 重抓

任何失敗:該指標回 None(不回 0、不回 50);
layer 端應將整個 dict 全 None 視為 "breadth_unavailable" → neutral,不阻塞流程。
"""

from datetime import datetime
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from loguru import logger
from selectolax.parser import HTMLParser
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config.settings import TIMEZONE_US_MARKET

HEADERS = {"User-Agent": "Mozilla/5.0"}
SELECTORS = [".last-quote", ".price", "span.quote"]


def _try_selectolax(html: str) -> Optional[float]:
    """主 parser - selectolax"""
    try:
        tree = HTMLParser(html)
        for sel in SELECTORS:
            node = tree.css_first(sel)
            if node:
                try:
                    return float(node.text(strip=True).replace(",", ""))
                except ValueError:
                    continue
    except Exception as e:
        logger.debug(f"selectolax parse failed: {e}")
    return None


def _try_bs4(html: str) -> Optional[float]:
    """備 parser - BeautifulSoup"""
    try:
        soup = BeautifulSoup(html, "html.parser")
        for sel in SELECTORS:
            node = soup.select_one(sel)
            if node:
                try:
                    return float(node.get_text(strip=True).replace(",", ""))
                except ValueError:
                    continue
    except Exception as e:
        logger.debug(f"BS4 parse failed: {e}")
    return None


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_breadth_indicator(symbol: str) -> Optional[float]:
    """抓 StockCharts 的廣度指標(例如 $NYHL, $SPXA50R, $SPXA200R)
    主 parser 失敗 fallback BS4;兩者皆失敗回 None。
    """
    url = f"https://stockcharts.com/h-sc/ui?s={symbol}"
    try:
        with httpx.Client(timeout=15.0, headers=HEADERS, follow_redirects=True) as client:
            r = client.get(url)
            r.raise_for_status()
            html = r.text

        val = _try_selectolax(html)
        if val is not None:
            return val
        logger.info(f"selectolax found nothing for {symbol}, trying BS4")
        val = _try_bs4(html)
        if val is None:
            logger.warning(f"breadth {symbol} unparseable in both parsers")
        return val
    except Exception as e:
        logger.error(f"fetch_breadth_indicator({symbol}) failed: {e}")
        return None


def get_breadth_snapshot() -> dict:
    """完整廣度快照。任何子指標失敗 = 該欄位 None;layer 端見全 None 視為 neutral。"""
    snapshot = {
        "spx_above_50ma_pct": None,
        "spx_above_200ma_pct": None,
        "nyse_new_highs": None,
        "advance_decline_line": None,
        "fetched_at": datetime.now(TIMEZONE_US_MARKET).isoformat(),
    }
    targets = {
        "spx_above_50ma_pct": "$SPXA50R",
        "spx_above_200ma_pct": "$SPXA200R",
        "nyse_new_highs": "$NYHL",
        "advance_decline_line": "$NYAD",
    }
    for key, sym in targets.items():
        try:
            snapshot[key] = fetch_breadth_indicator(sym)
        except Exception as e:
            logger.warning(f"breadth {key} retries exhausted: {e}")
            snapshot[key] = None
    return snapshot
