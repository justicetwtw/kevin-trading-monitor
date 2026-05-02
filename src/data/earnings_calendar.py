"""財報日曆(yfinance.calendar)— 提供 veto_checker 學習鎖第 3 條(財報前 7 天禁 short premium)

抓取對象:Tier A + Tier B 全部 universe(可由 caller 傳入其他子集)。
寫入:data_store/earnings_calendar.json
"""

from datetime import datetime, timedelta
from typing import Optional

import yfinance as yf
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config.settings import TIMEZONE_US_MARKET
from src.config.universe import TIER_A_CORE, TIER_B_SATELLITE
from src.storage.state_manager import read_json, write_json

EARNINGS_FILE = "earnings_calendar.json"
DEFAULT_SCAN_UNIVERSE = TIER_A_CORE + TIER_B_SATELLITE


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_earnings_date(symbol: str) -> dict:
    """抓單一標的下次財報日。yfinance.calendar 結構在不同版本變過,
    支援 dict / DataFrame 兩種回傳格式。
    """
    try:
        ticker = yf.Ticker(symbol)
        cal = ticker.calendar
        if cal is None:
            return {"symbol": symbol, "earnings_date": None}

        earnings_date = None
        if isinstance(cal, dict):
            earnings_date = cal.get("Earnings Date")
        else:
            try:
                if hasattr(cal, "index") and "Earnings Date" in cal.index:
                    earnings_date = cal.loc["Earnings Date"].iloc[0]
            except Exception:
                earnings_date = None

        if earnings_date is None:
            return {"symbol": symbol, "earnings_date": None}

        if isinstance(earnings_date, list) and earnings_date:
            earnings_date = earnings_date[0]

        return {
            "symbol": symbol,
            "earnings_date": str(earnings_date),
            "fetched_at": datetime.now(TIMEZONE_US_MARKET).isoformat(),
        }
    except Exception as e:
        logger.error(f"fetch_earnings_date({symbol}) failed: {e}")
        return {"symbol": symbol, "earnings_date": None}


def update_calendar(symbols: Optional[list] = None) -> dict:
    """更新指定 universe 的財報日曆。
    symbols=None 時掃 Tier A + Tier B(SELL_PUT_WHITELIST 同範圍)。
    寫入 data_store/earnings_calendar.json。
    """
    if symbols is None:
        symbols = DEFAULT_SCAN_UNIVERSE
    calendar = {}
    for s in symbols:
        info = fetch_earnings_date(s)
        if info.get("earnings_date"):
            calendar[s] = info
    write_json(EARNINGS_FILE, calendar)
    logger.info(f"Updated earnings calendar for {len(calendar)} / {len(symbols)} symbols")
    return calendar


def days_until_earnings(symbol: str) -> int:
    """讀快取,回傳距下次財報的天數;無資料回 999(視為「無財報風險」)。
    注意:Phase 1 上線首日尚未跑過 update_calendar 前,所有股票會回 999;
    veto_checker 端應以「天數 ≤ 7」為禁制條件,而非依賴 999 做正向判斷。
    """
    cal = read_json(EARNINGS_FILE, default={})
    if not isinstance(cal, dict) or symbol not in cal:
        return 999
    try:
        ed_str = cal[symbol]["earnings_date"]
        if not ed_str:
            return 999
        ed = _parse_earnings_date(ed_str)
        if ed is None:
            return 999
        now_us = datetime.now(TIMEZONE_US_MARKET).date()
        delta = (ed.date() - now_us).days
        return max(delta, 0)
    except Exception as e:
        logger.error(f"days_until_earnings({symbol}) parse failed: {e}")
        return 999


def _parse_earnings_date(ed_str: str) -> Optional[datetime]:
    """yfinance 回傳的 earnings_date 可能多種格式,逐一嘗試"""
    cleaned = ed_str.split("+")[0].strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def is_earnings_within_days(symbol: str, n_days: int = 7) -> bool:
    """學習鎖第 3 條 helper:財報前 N 天內 → True"""
    return days_until_earnings(symbol) <= n_days


def get_upcoming_earnings(within_days: int = 7) -> list:
    """讀快取,回傳 within_days 天內要公佈財報的所有 symbol(供 veto_checker 批次查)"""
    cal = read_json(EARNINGS_FILE, default={})
    if not isinstance(cal, dict):
        return []
    upcoming = []
    for sym in cal:
        d = days_until_earnings(sym)
        if d <= within_days:
            upcoming.append({"symbol": sym, "days_until": d,
                             "earnings_date": cal[sym].get("earnings_date")})
    return sorted(upcoming, key=lambda x: x["days_until"])
