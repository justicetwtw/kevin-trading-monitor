"""ETF 資金流 - SMH / QQQ / SPY(高風險 R4)

etf.com / etfdb 頁面結構常變,本模組設計上**強制走 cache fallback**:

  1. _fetch_etf_flow_raw(symbol) — 嘗試 scrape;頁面結構變動 → 抓不到欄位 → raise SchemaError
  2. _validate_schema(data)     — 必要欄位缺漏 → raise SchemaError
  3. fetch_etf_flow(symbol)     — 公開 API:
        - 抓取 + 驗證成功 → 寫快取(etf_flows_cache.json)、回傳實際資料
        - 抓取/驗證任一失敗 → 讀快取(可能是上週成功那筆),標 data_source="cache"
        - 快取也沒有(冷啟動)→ 回 {net_flow_usd: None, data_source: "cold_start"}

學習鎖友善設計:
- 永遠不回傳「假裝有資料的中性值」(0、placeholder 等)
- signals 端拿到 None / cold_start 必須視為「資料缺失」而非「過關」
"""

from datetime import datetime
from typing import Optional

import httpx
from loguru import logger
from selectolax.parser import HTMLParser
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config.settings import TIMEZONE_US_MARKET
from src.storage.state_manager import read_json, write_json

HEADERS = {"User-Agent": "Mozilla/5.0"}
CACHE_FILE = "etf_flows_cache.json"

REQUIRED_SCHEMA_FIELDS = ("symbol", "estimated_net_flow_usd", "lookback_days")


class SchemaError(ValueError):
    """頁面結構變動或必要欄位缺漏"""


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _fetch_etf_flow_raw(symbol: str, lookback_days: int = 5) -> dict:
    """從 etfdb 抓資金流。
    Phase 2 etfdb 頁面結構複雜未實裝實際萃取 → 直接 raise SchemaError 進 cache fallback。
    Phase 3 替換為穩定來源(可能 etf.com 的 daily flow API 或 ETF.com 月報 PDF)。
    """
    url = f"https://etfdb.com/etf/{symbol}/#flows"
    try:
        with httpx.Client(timeout=15.0, headers=HEADERS, follow_redirects=True) as c:
            r = c.get(url)
            r.raise_for_status()
            # Phase 2 暫不萃取(頁面 JS 渲染,靜態 HTML 找不到 flow 數字)
            HTMLParser(r.text)
        # 故意 raise — Phase 3 來源穩定後改為實際解析並回傳完整 dict
        raise SchemaError(
            f"etfdb extraction not implemented for Phase 2 ({symbol}); "
            "force cache fallback path"
        )
    except SchemaError:
        raise
    except Exception as e:
        logger.warning(f"_fetch_etf_flow_raw({symbol}) network/parse error: {e}")
        raise SchemaError(f"raw fetch failed: {e}") from e


def _validate_schema(data: dict) -> None:
    """必要欄位缺漏 → raise"""
    missing = [k for k in REQUIRED_SCHEMA_FIELDS if k not in data]
    if missing:
        raise SchemaError(f"missing fields: {missing}")
    if data.get("estimated_net_flow_usd") is None:
        raise SchemaError("estimated_net_flow_usd is None — not a valid measurement")


def _load_from_cache(symbol: str) -> Optional[dict]:
    """讀 cache;沒有就回 None"""
    cache = read_json(CACHE_FILE, default={})
    if not isinstance(cache, dict):
        return None
    return cache.get(symbol)


def _write_to_cache(symbol: str, data: dict) -> None:
    cache = read_json(CACHE_FILE, default={})
    if not isinstance(cache, dict):
        cache = {}
    cache[symbol] = {**data, "cached_at": datetime.now(TIMEZONE_US_MARKET).isoformat()}
    write_json(CACHE_FILE, cache)


def fetch_etf_flow(symbol: str, lookback_days: int = 5) -> dict:
    """公開 API。永遠回字典,但 net_flow 可能為 None。

    回傳 schema:
      {
        "symbol": str,
        "estimated_net_flow_usd": float | None,
        "lookback_days": int,
        "data_source": "live" | "cache" | "cold_start",
        "fetched_at": iso str,
      }
    """
    fetched_at = datetime.now(TIMEZONE_US_MARKET).isoformat()

    # 1. 嘗試 live
    try:
        raw = _fetch_etf_flow_raw(symbol, lookback_days)
        _validate_schema(raw)
        result = {
            "symbol": symbol,
            "estimated_net_flow_usd": raw["estimated_net_flow_usd"],
            "lookback_days": raw["lookback_days"],
            "data_source": "live",
            "fetched_at": fetched_at,
        }
        _write_to_cache(symbol, result)
        return result
    except SchemaError as e:
        logger.info(f"etf_flow {symbol} schema/fetch failed → cache fallback: {e}")
    except Exception as e:
        logger.error(f"etf_flow {symbol} unexpected error → cache fallback: {e}")

    # 2. cache fallback
    cached = _load_from_cache(symbol)
    if cached:
        return {
            **cached,
            "data_source": "cache",
            "fetched_at": fetched_at,
        }

    # 3. 冷啟動 — 明確回 None,絕不偽造中性值
    logger.warning(f"etf_flow {symbol} cold start (no cache) → net_flow=None")
    return {
        "symbol": symbol,
        "estimated_net_flow_usd": None,
        "lookback_days": lookback_days,
        "data_source": "cold_start",
        "fetched_at": fetched_at,
    }


def get_smh_qqq_flows() -> dict:
    return {
        "SMH": fetch_etf_flow("SMH", 5),
        "QQQ": fetch_etf_flow("QQQ", 5),
        "SPY": fetch_etf_flow("SPY", 5),
    }
