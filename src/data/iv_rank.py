"""IV Rank / IV Percentile 計算(維護 252 日歷史)"""

import json
from datetime import datetime
from typing import Optional

import yfinance as yf
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config.settings import TIMEZONE_US_MARKET
from src.storage.state_manager import DATA_STORE_DIR

IV_HISTORY_PATH = DATA_STORE_DIR / "iv_history.json"
MIN_SAMPLES_FOR_RANK = 30  # 不足 30 天歷史不出 IVR/IVP,回 None


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def get_atm_iv(symbol: str) -> Optional[float]:
    """取當下 ATM 選擇權的 IV(取最接近 35 DTE 的那期 ATM,call+put 平均)"""
    try:
        ticker = yf.Ticker(symbol)
        if not ticker.options:
            return None

        today = datetime.now(TIMEZONE_US_MARKET).date()
        best_exp = None
        best_dte_diff = 999
        for exp in ticker.options:
            dte = (datetime.strptime(exp, "%Y-%m-%d").date() - today).days
            if 25 <= dte <= 50 and abs(dte - 35) < best_dte_diff:
                best_exp = exp
                best_dte_diff = abs(dte - 35)
        if not best_exp:
            best_exp = ticker.options[0]

        chain = ticker.option_chain(best_exp)
        try:
            underlying = float(ticker.fast_info.get("lastPrice", 0))
        except Exception:
            underlying = 0.0
        if not underlying:
            hist = ticker.history(period="1d")
            if hist.empty:
                return None
            underlying = float(hist["Close"].iloc[-1])

        calls = chain.calls.copy()
        puts = chain.puts.copy()
        if calls.empty or puts.empty:
            return None
        calls["dist"] = (calls["strike"] - underlying).abs()
        puts["dist"] = (puts["strike"] - underlying).abs()
        atm_call_iv = calls.nsmallest(1, "dist")["impliedVolatility"].iloc[0]
        atm_put_iv = puts.nsmallest(1, "dist")["impliedVolatility"].iloc[0]
        return float((atm_call_iv + atm_put_iv) / 2)
    except Exception as e:
        logger.error(f"get_atm_iv({symbol}) failed: {e}")
        return None


def update_iv_history(symbol: str) -> None:
    """每日跑一次,把當日 ATM IV 記錄下來"""
    iv = get_atm_iv(symbol)
    if iv is None:
        return
    today = datetime.now(TIMEZONE_US_MARKET).strftime("%Y-%m-%d")

    history = {}
    if IV_HISTORY_PATH.exists():
        try:
            with open(IV_HISTORY_PATH, "r", encoding="utf-8") as f:
                history = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"iv_history.json corrupted: {e}; starting fresh")
            history = {}

    if symbol not in history:
        history[symbol] = {}
    history[symbol][today] = iv

    # 保留最近 300 天
    if len(history[symbol]) > 300:
        sorted_dates = sorted(history[symbol].keys())
        for d in sorted_dates[:-300]:
            del history[symbol][d]

    with open(IV_HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)


def calc_iv_rank(symbol: str, lookback: int = 252) -> dict:
    """計算 IVR / IVP
    IVR = (current_IV - min_IV) / (max_IV - min_IV) × 100
    IVP = % of days IV was below current

    第一次跑(history 不存在 or 樣本 < 30)→ ivr/ivp 全部回 None,
    避免下游被「中性 50」誤判為過關。
    """
    if not IV_HISTORY_PATH.exists():
        return {"ivr": None, "ivp": None, "current_iv": None, "samples": 0}

    try:
        with open(IV_HISTORY_PATH, "r", encoding="utf-8") as f:
            history = json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"iv_history.json corrupted: {e}")
        return {"ivr": None, "ivp": None, "current_iv": None, "samples": 0}

    if symbol not in history or len(history[symbol]) < MIN_SAMPLES_FOR_RANK:
        return {
            "ivr": None,
            "ivp": None,
            "current_iv": None,
            "samples": len(history.get(symbol, {})),
        }

    sorted_items = sorted(history[symbol].items())[-lookback:]
    ivs = [v for _, v in sorted_items]
    current = ivs[-1]
    min_iv = min(ivs)
    max_iv = max(ivs)

    # max == min(全部值相同)情境極罕見,但代表 IV 完全沒波動歷史 → 不可信,回 None
    # (絕不能回 50 — 會被學習鎖第 2 條判為「IVR ≥ 30 過關」誤觸發 short premium 訊號)
    if max_iv > min_iv:
        ivr = (current - min_iv) / (max_iv - min_iv) * 100
    else:
        ivr = None
    ivp = sum(1 for iv in ivs if iv < current) / len(ivs) * 100

    return {
        "ivr": round(ivr, 1) if ivr is not None else None,
        "ivp": round(ivp, 1),
        "current_iv": round(current, 4),
        "min_iv": round(min_iv, 4),
        "max_iv": round(max_iv, 4),
        "samples": len(ivs),
    }
