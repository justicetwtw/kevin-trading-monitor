"""FRED API - 殖利率 / 信用利差 / DXY / GDP / CPI

FRED_API_KEY 從 src.config.settings 集中讀取。
未設定時 get_fred_client() 會 raise ValueError,fetch_series 也讓它向上傳播,
不允許靜默 fallback 回空資料(避免下游把「沒資料」誤判為「綠燈」)。
"""

import math
from datetime import datetime, timedelta
from typing import Optional

from fredapi import Fred
from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.config.settings import FRED_API_KEY

# FRED Series ID 對照
FRED_SERIES = {
    "treasury_10y": "DGS10",
    "treasury_2y": "DGS2",
    "treasury_3m": "DGS3MO",
    "hy_oas": "BAMLH0A0HYM2",       # ICE BofA US High Yield OAS
    "ig_oas": "BAMLC0A0CM",          # IG OAS
    "dxy": "DTWEXBGS",               # 廣義貿易加權美元指數
    "vix_fred": "VIXCLS",
    "cpi": "CPIAUCSL",
    "gdp": "GDP",
    "unrate": "UNRATE",
    "fed_funds": "FEDFUNDS",
}


def get_fred_client() -> Fred:
    """建立 FRED client。未設 FRED_API_KEY 直接 raise(不允許靜默 fallback)"""
    if not FRED_API_KEY:
        raise ValueError(
            "FRED_API_KEY not set. Configure it in environment or GitHub Secrets; "
            "fred_api refuses to silently return empty data."
        )
    return Fred(api_key=FRED_API_KEY)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    # ValueError(missing key)不重試也不吞,讓它直接傳播給呼叫端
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
)
def fetch_series(series_id: str, lookback_days: int = 60) -> list:
    """抓單一 FRED series 的近期觀測值。
    回傳 [(date_str, value), ...]
    """
    try:
        fred = get_fred_client()
        end = datetime.now()
        start = end - timedelta(days=lookback_days)
        data = fred.get_series(series_id, start, end)
        return [(str(idx.date()), float(val))
                for idx, val in data.items() if not _is_nan(val)]
    except ValueError:
        # FRED_API_KEY 未設定 → 向上拋,不允許 fallback
        raise
    except Exception as e:
        logger.error(f"FRED fetch_series({series_id}) failed: {e}")
        return []


def _is_nan(v) -> bool:
    try:
        return math.isnan(v)
    except (TypeError, ValueError):
        return v is None


def get_yield_curve_spread() -> Optional[float]:
    """10Y-2Y 殖利率差(bps)"""
    y10 = fetch_series(FRED_SERIES["treasury_10y"], lookback_days=10)
    y2 = fetch_series(FRED_SERIES["treasury_2y"], lookback_days=10)
    if not y10 or not y2:
        return None
    return (y10[-1][1] - y2[-1][1]) * 100  # 轉 bps


def get_hy_credit_spread() -> Optional[float]:
    """HY 信用利差(bps)"""
    data = fetch_series(FRED_SERIES["hy_oas"], lookback_days=10)
    return data[-1][1] * 100 if data else None


def get_dxy() -> Optional[float]:
    """DXY 美元指數"""
    data = fetch_series(FRED_SERIES["dxy"], lookback_days=10)
    return data[-1][1] if data else None


def get_macro_snapshot() -> dict:
    """完整宏觀快照"""
    return {
        "yield_curve_spread_bps": get_yield_curve_spread(),
        "hy_oas_bps": get_hy_credit_spread(),
        "dxy": get_dxy(),
        "fetched_at": datetime.utcnow().isoformat(),
    }
