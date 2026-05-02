"""台股主動 ETF 持股 - 證交所 OpenAPI(t187ap47_L)

universe 來源:src.config.universe.TWSTOCK_ACTIVE_ETFS(6 檔精選)
寫入:data_store/active_etf_holdings.json — 保留最近 60 天每日快照,支援 N 天比對。
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config.settings import TIMEZONE_TW_MARKET
from src.config.universe import TWSTOCK_ACTIVE_ETFS
from src.storage.state_manager import read_json, write_json

ACTIVE_ETF_HOLDINGS_FILE = "active_etf_holdings.json"
HEADERS = {"User-Agent": "Mozilla/5.0"}
TWSE_OPENAPI = "https://openapi.twse.com.tw/v1/opendata/t187ap47_L"
MIN_DIFF_PCT_FOR_SIGNAL = 0.5  # 持股權重變動 ≥0.5% 才算訊號


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_etf_holdings(etf_symbol: str) -> list:
    """抓單檔主動 ETF 持股(去 .TW 後綴)。失敗 / 無資料 → 回 []。"""
    code = etf_symbol.replace(".TW", "").replace(".TWO", "")
    try:
        with httpx.Client(timeout=20.0, headers=HEADERS) as c:
            r = c.get(TWSE_OPENAPI)
            r.raise_for_status()
            data = r.json()
            holdings = [item for item in data
                        if item.get("基金統一編號") == code
                        or item.get("基金代號") == code]
            return [{
                "symbol": h.get("持股代號", ""),
                "name": h.get("持股名稱", ""),
                "weight_pct": float(h.get("持股比例", 0) or 0),
                "shares": int(float(h.get("持股股數", 0) or 0)),
            } for h in holdings]
    except Exception as e:
        logger.warning(f"fetch_etf_holdings({etf_symbol}) failed: {e}")
        return []


def update_all_active_etf_holdings() -> dict:
    """更新全部主動 ETF 持股快取,當日鍵覆蓋。保留最近 60 天。"""
    today = datetime.now(TIMEZONE_TW_MARKET).strftime("%Y-%m-%d")
    history = read_json(ACTIVE_ETF_HOLDINGS_FILE, default={})
    if not isinstance(history, dict):
        history = {}

    for etf in TWSTOCK_ACTIVE_ETFS:
        sym = etf["symbol"]
        try:
            holdings = fetch_etf_holdings(sym)
        except Exception as e:
            logger.warning(f"update_all skipping {sym}: {e}")
            continue
        if not holdings:
            continue
        if sym not in history:
            history[sym] = {}
        history[sym][today] = holdings

        # 保留最近 60 天
        if len(history[sym]) > 60:
            keys = sorted(history[sym].keys())
            for k in keys[:-60]:
                del history[sym][k]

    write_json(ACTIVE_ETF_HOLDINGS_FILE, history)
    logger.info(f"Updated {len(history)} ETFs holdings")
    return history


def get_holdings_change(etf_symbol: str, lookback_days: int = 7) -> dict:
    """比較某檔主動 ETF 過去 N 天的持股權重變化(≥0.5% 才回報)"""
    history = read_json(ACTIVE_ETF_HOLDINGS_FILE, default={})
    if not isinstance(history, dict) or etf_symbol not in history:
        return {}
    dates = sorted(history[etf_symbol].keys())
    if len(dates) < 2:
        return {}

    cutoff = (datetime.now(TIMEZONE_TW_MARKET) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    old_dates = [d for d in dates if d <= cutoff]
    if not old_dates:
        return {}

    old_date = old_dates[-1]
    new_date = dates[-1]
    old_h = {h["symbol"]: h["weight_pct"] for h in history[etf_symbol][old_date]}
    new_h = {h["symbol"]: h["weight_pct"] for h in history[etf_symbol][new_date]}

    changes = {}
    for sym in set(old_h.keys()) | set(new_h.keys()):
        old_w = old_h.get(sym, 0)
        new_w = new_h.get(sym, 0)
        diff = new_w - old_w
        if abs(diff) >= MIN_DIFF_PCT_FOR_SIGNAL:
            changes[sym] = {"old": old_w, "new": new_w, "diff_pct": diff}
    return changes


def aggregate_cross_etf_signals(lookback_days: int = 7) -> dict:
    """聚合跨主動 ETF 訊號(三級訊號用):
    某 symbol 被幾檔主動 ETF 同方向加減碼 → 訊號越強。
    """
    aggregate = defaultdict(lambda: {"increased_etfs": [], "decreased_etfs": []})

    for etf in TWSTOCK_ACTIVE_ETFS:
        changes = get_holdings_change(etf["symbol"], lookback_days)
        for sym, ch in changes.items():
            if ch["diff_pct"] > 0:
                aggregate[sym]["increased_etfs"].append({
                    "etf": etf["symbol"],
                    "etf_name": etf["name"],
                    "diff_pct": ch["diff_pct"],
                })
            else:
                aggregate[sym]["decreased_etfs"].append({
                    "etf": etf["symbol"],
                    "etf_name": etf["name"],
                    "diff_pct": ch["diff_pct"],
                })
    return dict(aggregate)
