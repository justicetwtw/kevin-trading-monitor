"""Put/Call Ratio - CBOE 主、yfinance ^CPC 備"""

from datetime import datetime
from typing import Optional

import yfinance as yf
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential


HEADERS = {"User-Agent": "Mozilla/5.0"}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_pcr_from_cboe() -> Optional[float]:
    """從 CBOE 抓 daily total PCR(目前 CBOE 頁面結構不穩定,直接走 fallback)"""
    try:
        # CBOE 的 PCR 頁面 scraping 在歷史上多次變動;
        # 階段 2 暫保留接口、回 None 由 fallback 接手。
        # 階段 3 視穩定來源改寫(可能是 CBOE OptionsMarketStatistics CSV)。
        return None
    except Exception as e:
        logger.error(f"fetch_pcr_from_cboe failed: {e}")
        return None


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_pcr_from_yfinance() -> Optional[float]:
    """fallback - yfinance ^CPC(部分時期可能無資料)"""
    try:
        ticker = yf.Ticker("^CPC")
        df = ticker.history(period="5d")
        if df.empty:
            return None
        return float(df["Close"].iloc[-1])
    except Exception as e:
        logger.error(f"fetch_pcr_from_yfinance failed: {e}")
        return None


def get_put_call_ratio() -> dict:
    """主備雙重來源"""
    try:
        pcr = fetch_pcr_from_cboe()
    except Exception as e:
        logger.warning(f"CBOE PCR retries exhausted: {e}")
        pcr = None
    source = "cboe"
    if pcr is None:
        try:
            pcr = fetch_pcr_from_yfinance()
        except Exception as e:
            logger.warning(f"yfinance PCR retries exhausted: {e}")
            pcr = None
        source = "yfinance"
    return {
        "pcr": pcr,
        "source": source,
        "fetched_at": datetime.utcnow().isoformat(),
    }
