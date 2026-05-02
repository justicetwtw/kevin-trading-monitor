"""台股資料 - yfinance .TW 為主、twstock 套件當備援

twstock import 失敗也要能跑(只是 fallback 不可用)。
"""

from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config.settings import TIMEZONE_TW_MARKET

try:
    import twstock  # type: ignore
    TWSTOCK_AVAILABLE = True
except ImportError as _e:
    TWSTOCK_AVAILABLE = False
    twstock = None  # type: ignore
    logger.warning(f"twstock package not available, falling back to yfinance only: {_e}")


def _ensure_tw_suffix(symbol: str) -> str:
    """確保 .TW 後綴(.TWO 上櫃也保留)"""
    if symbol.endswith(".TW") or symbol.endswith(".TWO"):
        return symbol
    return f"{symbol}.TW"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _fetch_yf(symbol: str, period: str) -> pd.DataFrame:
    """yfinance 抓取,失敗會被 retry"""
    ticker = yf.Ticker(_ensure_tw_suffix(symbol))
    df = ticker.history(period=period)
    if df.empty:
        return pd.DataFrame()
    return df


def _fetch_twstock_fallback(symbol: str) -> pd.DataFrame:
    """twstock 套件 fallback。只抓最近 ~31 天(套件限制),用於 yfinance 全失敗時救急。
    twstock 未裝 → 回空 DataFrame。
    """
    if not TWSTOCK_AVAILABLE:
        return pd.DataFrame()
    code = symbol.replace(".TW", "").replace(".TWO", "")
    try:
        stock = twstock.Stock(code)
        # twstock fetch_31() 抓最近 31 個交易日
        rows = stock.fetch_31()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame([{
            "Date": r.date,
            "Open": r.open,
            "High": r.high,
            "Low": r.low,
            "Close": r.close,
            "Volume": r.capacity,
        } for r in rows])
        df = df.set_index("Date")
        return df
    except Exception as e:
        logger.error(f"_fetch_twstock_fallback({symbol}) failed: {e}")
        return pd.DataFrame()


def fetch_tw_history(symbol: str, period: str = "1y") -> pd.DataFrame:
    """台股歷史價。yfinance 主、twstock 備。雙源失敗 → 回空 DataFrame。"""
    try:
        df = _fetch_yf(symbol, period)
        if not df.empty:
            return df
    except Exception as e:
        logger.warning(f"yfinance .TW retries exhausted for {symbol}: {e}")

    logger.info(f"falling back to twstock for {symbol}")
    return _fetch_twstock_fallback(symbol)


def get_tw_latest_price(symbol: str) -> Optional[float]:
    df = fetch_tw_history(symbol, period="5d")
    if df.empty:
        return None
    return float(df["Close"].iloc[-1])


def get_tw_52w_metrics(symbol: str) -> dict:
    df = fetch_tw_history(symbol, period="1y")
    if df.empty:
        return {
            "high": None, "low": None, "current": None,
            "pct_from_high": None, "pct_from_low": None,
        }
    high = float(df["High"].max())
    low = float(df["Low"].min())
    current = float(df["Close"].iloc[-1])
    return {
        "high": high,
        "low": low,
        "current": current,
        "pct_from_high": (current - high) / high,
        "pct_from_low": (current - low) / low,
        "fetched_at": datetime.now(TIMEZONE_TW_MARKET).isoformat(),
    }
