"""分析師動向(yfinance.upgrades_downgrades)

7 天內 ≥2 家上調 → has_recent_upgrades 回 True(供 sell_call veto:
 不在「明顯獲市場吹捧」當下 short 上方 call)
"""

from datetime import datetime, timedelta
from typing import Optional

import yfinance as yf
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config.settings import TIMEZONE_US_MARKET


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_analyst_actions(symbol: str, lookback_days: int = 7) -> dict:
    """抓某檔過去 N 天的分析師動作。任何失敗 → 上下調計數 0、actions 空 list。"""
    try:
        ticker = yf.Ticker(symbol)
        ud = getattr(ticker, "upgrades_downgrades", None)
        if ud is None or ud.empty:
            return {"symbol": symbol, "upgrades": 0, "downgrades": 0,
                    "actions": [], "lookback_days": lookback_days}

        cutoff = datetime.now(TIMEZONE_US_MARKET) - timedelta(days=lookback_days)
        # tz 標準化
        if ud.index.tz is None:
            ud.index = ud.index.tz_localize("UTC").tz_convert(TIMEZONE_US_MARKET)
        else:
            ud.index = ud.index.tz_convert(TIMEZONE_US_MARKET)

        recent = ud[ud.index >= cutoff]
        actions = []
        upgrades = 0
        downgrades = 0
        for idx, row in recent.iterrows():
            grade = str(row.get("ToGrade", "")).lower()
            action = str(row.get("Action", "")).lower()
            firm = row.get("Firm", "")

            is_up = (
                "buy" in grade or "outperform" in grade or "overweight" in grade
                or action in ("upgraded", "init", "main")
            )
            is_down = (
                "sell" in grade or "underperform" in grade
                or action == "downgraded"
            )
            if is_up and not is_down:
                upgrades += 1
                actions.append({"date": str(idx), "firm": firm,
                                "to": grade, "type": "upgrade"})
            elif is_down:
                downgrades += 1
                actions.append({"date": str(idx), "firm": firm,
                                "to": grade, "type": "downgrade"})

        return {
            "symbol": symbol,
            "upgrades": upgrades,
            "downgrades": downgrades,
            "actions": actions,
            "lookback_days": lookback_days,
        }
    except Exception as e:
        logger.error(f"fetch_analyst_actions({symbol}) failed: {e}")
        return {"symbol": symbol, "upgrades": 0, "downgrades": 0,
                "actions": [], "lookback_days": lookback_days}


def has_recent_upgrades(symbol: str, n_min: int = 2, lookback_days: int = 7) -> bool:
    """7 天內 ≥ n_min 家上調 → True(供 sell_call veto / final_scorer 加分)"""
    return fetch_analyst_actions(symbol, lookback_days)["upgrades"] >= n_min


def has_recent_downgrades(symbol: str, n_min: int = 2, lookback_days: int = 7) -> bool:
    return fetch_analyst_actions(symbol, lookback_days)["downgrades"] >= n_min
