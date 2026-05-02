"""基本面儀表板(yfinance.info / quarterly_earnings)

抓:PE / Forward PE / PEG / PB / PS / EPS 成長率 / FCF Yield / ROE / 毛利率 / 營業利益率 /
    營收 YoY / 盈餘 YoY / market_cap / sector / industry。
寫入:data_store/fundamentals_snapshot.json
"""

from datetime import datetime
from typing import Optional

import yfinance as yf
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config.settings import TIMEZONE_US_MARKET
from src.config.universe import TIER_A_CORE, TIER_B_SATELLITE
from src.storage.state_manager import write_json

FUNDAMENTALS_FILE = "fundamentals_snapshot.json"
DEFAULT_SCAN_UNIVERSE = TIER_A_CORE + TIER_B_SATELLITE


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_fundamentals(symbol: str) -> dict:
    """單一標的基本面快照。任何欄位失敗 → 該欄位 None,絕不偽造中性值。"""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        return {
            "symbol": symbol,
            "pe_trailing": info.get("trailingPE"),
            "pe_forward": info.get("forwardPE"),
            "peg": info.get("pegRatio"),
            "pb": info.get("priceToBook"),
            "ps": info.get("priceToSalesTrailing12Months"),
            "fcf_yield": _calc_fcf_yield(info),
            "roe": info.get("returnOnEquity"),
            "gross_margin": info.get("grossMargins"),
            "operating_margin": info.get("operatingMargins"),
            "rev_growth_yoy": info.get("revenueGrowth"),
            "earnings_growth_yoy": info.get("earningsGrowth"),
            "market_cap": info.get("marketCap"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "fetched_at": datetime.now(TIMEZONE_US_MARKET).isoformat(),
        }
    except Exception as e:
        logger.error(f"fetch_fundamentals({symbol}) failed: {e}")
        return {"symbol": symbol, "fetched_at": datetime.now(TIMEZONE_US_MARKET).isoformat()}


def _calc_fcf_yield(info: dict) -> Optional[float]:
    """FCF Yield = Free Cash Flow / Market Cap"""
    fcf = info.get("freeCashflow")
    mcap = info.get("marketCap")
    if fcf and mcap and mcap > 0:
        return fcf / mcap
    return None


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_eps_history(symbol: str, n_quarters: int = 4) -> list:
    """過去 N 季 EPS(用於偵測 EPS miss / consecutive decline)"""
    try:
        ticker = yf.Ticker(symbol)
        earnings = getattr(ticker, "quarterly_earnings", None)
        if earnings is None or earnings.empty:
            return []
        df = earnings.head(n_quarters)
        return [
            {"quarter": str(idx), "eps": float(row.get("Earnings", 0))}
            for idx, row in df.iterrows()
        ]
    except Exception as e:
        logger.error(f"fetch_eps_history({symbol}) failed: {e}")
        return []


def detect_consecutive_eps_miss(symbol: str, n_quarters: int = 2) -> bool:
    """連續 N 季 EPS 衰退(用於 LEAPS 否決)。資料不足 → False(保守不誤觸發否決)"""
    history = fetch_eps_history(symbol, n_quarters + 1)
    if len(history) < n_quarters + 1:
        return False
    for i in range(n_quarters):
        if history[i]["eps"] >= history[i + 1]["eps"]:
            return False
    return True


def update_fundamentals_snapshot(symbols: Optional[list] = None) -> dict:
    """更新整批 universe 的基本面快照,寫入 data_store/fundamentals_snapshot.json。"""
    if symbols is None:
        symbols = DEFAULT_SCAN_UNIVERSE
    snapshot = {
        "fetched_at": datetime.now(TIMEZONE_US_MARKET).isoformat(),
        "symbols": {},
    }
    for s in symbols:
        snapshot["symbols"][s] = fetch_fundamentals(s)
    write_json(FUNDAMENTALS_FILE, snapshot)
    logger.info(f"Updated fundamentals snapshot for {len(symbols)} symbols")
    return snapshot
