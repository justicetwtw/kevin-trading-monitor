"""TSMC(2330)月營收 - 公開資訊觀測站(MOPS)

頁面用 big5 編碼;每月 10 日左右公告前一月。
寫入:data_store/tsmc_revenue_history.json — 累積歷史,supports YoY trend analysis。
"""

import re
from datetime import datetime
from typing import Optional

import httpx
from loguru import logger
from selectolax.parser import HTMLParser
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config.settings import TIMEZONE_US_MARKET
from src.storage.state_manager import read_json, write_json

REVENUE_HISTORY_FILE = "tsmc_revenue_history.json"
HEADERS = {"User-Agent": "Mozilla/5.0"}
MOPS_URL = "https://mops.twse.com.tw/nas/t21/sii/t21sc03_2330_0.html"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_tsmc_monthly_revenue() -> dict:
    """從 MOPS 抓 TSMC 最新月營收。失敗 / 解析不到 → 回 {}。"""
    try:
        with httpx.Client(timeout=20.0, headers=HEADERS, follow_redirects=True) as c:
            r = c.get(MOPS_URL)
            r.encoding = "big5"
            r.raise_for_status()
            tree = HTMLParser(r.text)
            tables = tree.css("table")
            for tbl in tables:
                rows = tbl.css("tr")
                for row in rows:
                    cells = [c.text(strip=True) for c in row.css("td")]
                    # 預期格式: [民國年/月, 當月營收, 去年同月, YoY%, 累計, 累計YoY]
                    if len(cells) >= 6 and re.match(r"\d{3,4}/\d{1,2}", cells[0]):
                        try:
                            yoy_pct = _parse_pct(cells[3])
                            ytd_yoy_pct = _parse_pct(cells[5])
                            return {
                                "year_month": cells[0],
                                "current_revenue": cells[1],
                                "prev_year_revenue": cells[2],
                                "yoy_pct": yoy_pct,
                                "ytd_revenue": cells[4],
                                "ytd_yoy_pct": ytd_yoy_pct,
                                "fetched_at": datetime.now(TIMEZONE_US_MARKET).isoformat(),
                                "source": "MOPS",
                            }
                        except (ValueError, IndexError) as e:
                            logger.debug(f"Parse row failed: {e}")
                            continue
        return {}
    except Exception as e:
        logger.error(f"fetch_tsmc_monthly_revenue failed: {e}")
        return {}


def _parse_pct(s: str) -> Optional[float]:
    cleaned = s.replace("%", "").replace(",", "").strip()
    if not cleaned or cleaned == "-":
        return None
    return float(cleaned) / 100


def update_revenue_history() -> dict:
    """抓當期數據,合併進 data_store/tsmc_revenue_history.json。
    key 用 year_month(民國年/月),同月覆蓋(MOPS 偶有更新)。
    """
    latest = fetch_tsmc_monthly_revenue()
    if not latest or not latest.get("year_month"):
        logger.warning("update_revenue_history: no new data")
        return read_json(REVENUE_HISTORY_FILE, default={})

    history = read_json(REVENUE_HISTORY_FILE, default={})
    if not isinstance(history, dict):
        history = {}
    history[latest["year_month"]] = latest
    write_json(REVENUE_HISTORY_FILE, history)
    logger.info(f"TSMC revenue history updated for {latest['year_month']}")
    return history


def get_latest_yoy() -> Optional[float]:
    """讀快取,回最新 YoY%(浮點數,如 0.45 = 45%)。冷啟動 → None,signals 端不可誤判過關。"""
    history = read_json(REVENUE_HISTORY_FILE, default={})
    if not isinstance(history, dict) or not history:
        return None
    latest_key = sorted(history.keys())[-1]
    return history[latest_key].get("yoy_pct")
