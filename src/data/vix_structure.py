"""VIX 期貨結構 - VIX / VIX9D / VIX3M

提供:
- fetch_vix_term_structure() : 三點期限結構 + 倒掛旗標
- is_vix_consecutive_above()  : 學習鎖第 4 條(連 3 天 VIX > 30 禁 long premium)
"""

from typing import Optional

import yfinance as yf
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _fetch_close(symbol: str, period: str = "5d") -> Optional[float]:
    """抓某 symbol 最新收盤(內部 helper,讓 retry 細粒度套到單次 API call 上)"""
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period)
    if df.empty:
        return None
    return float(df["Close"].iloc[-1])


def fetch_vix_term_structure() -> dict:
    """VIX 短中長期結構"""
    out = {}
    for label, sym in [("vix", "^VIX"), ("vix9d", "^VIX9D"), ("vix3m", "^VIX3M")]:
        try:
            out[label] = _fetch_close(sym)
        except Exception as e:
            logger.error(f"fetch_vix({sym}) failed: {e}")
            out[label] = None

    # 倒掛標記
    if out.get("vix") is not None and out.get("vix9d") is not None:
        out["vix9d_inverted"] = out["vix9d"] > out["vix"]
    if out.get("vix") is not None and out.get("vix3m") is not None:
        out["vix3m_inverted"] = out["vix"] > out["vix3m"]
    return out


def fetch_vix_asof() -> Optional[str]:
    """回傳最新 ^VIX bar 的日期(ISO 字串),供 freshness 判斷;失敗回 None。"""
    try:
        ticker = yf.Ticker("^VIX")
        df = ticker.history(period="5d")
        if df.empty:
            return None
        last = df.index[-1]
        return last.isoformat() if hasattr(last, "isoformat") else str(last)
    except Exception as e:
        logger.error(f"fetch_vix_asof failed: {e}")
        return None


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def is_vix_consecutive_above(threshold: float = 30, n_days: int = 3) -> bool:
    """檢查 VIX 是否連續 N 天 > threshold(學習鎖第 4 條)"""
    try:
        ticker = yf.Ticker("^VIX")
        df = ticker.history(period=f"{n_days + 5}d")
        if df.empty or len(df) < n_days:
            return False
        recent = df["Close"].iloc[-n_days:]
        return all(v > threshold for v in recent)
    except Exception as e:
        logger.error(f"is_vix_consecutive_above failed: {e}")
        return False
