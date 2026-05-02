"""台股核心訊號(v4 邏輯):00631L + 2330 三級加碼。

三級條件(對應 TWSTOCK_TIER_RULES):
  A:距 52W 高 ≤ -10% AND 週 RSI < 40                 → deploy 25%
  B:距 52W 高 ≤ -20% AND 週 RSI < 35                 → deploy 35%
  C:距 52W 高 ≤ -30% AND 週 RSI < 30 AND VIX > 35    → deploy 40%

Cooldown:加碼後 14 天內,tier 仍計算但 cooldown=True、alert_level 降 white。
"""

from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from loguru import logger

from src.config.settings import TIMEZONE_TW_MARKET
from src.config.thresholds import TWSTOCK_TIER_RULES, TWSTOCK_MIN_DAYS_BETWEEN_DEPLOYMENTS
from src.data.twstock_data import fetch_tw_history, get_tw_52w_metrics
from src.data.vix_structure import fetch_vix_term_structure
from src.indicators.basic import get_rsi_latest
from src.storage.state_manager import read_json, write_json

DEPLOYMENT_LOG_FILE = "twstock_deployment_log.json"


# ============================
# Cooldown(state 檔操作)
# ============================

def mark_deployed(symbol: str, tier: str) -> dict:
    """使用者手動觸發:寫入加碼紀錄。tier ∈ {"A", "B", "C"}。"""
    log = read_json(DEPLOYMENT_LOG_FILE, default={})
    if not isinstance(log, dict):
        log = {}
    today = datetime.now(TIMEZONE_TW_MARKET).date().isoformat()
    log[symbol] = {"last_deploy_date": today, "last_tier": tier}
    write_json(DEPLOYMENT_LOG_FILE, log)
    logger.info(f"mark_deployed: {symbol} tier={tier} on {today}")
    return log[symbol]


def get_cooldown_status(symbol: str) -> dict:
    """回傳 {in_cooldown: bool, days_remaining: int, last_deploy_date: str|None, last_tier: str|None}"""
    log = read_json(DEPLOYMENT_LOG_FILE, default={})
    if not isinstance(log, dict) or symbol not in log:
        return {"in_cooldown": False, "days_remaining": 0,
                "last_deploy_date": None, "last_tier": None}
    rec = log[symbol]
    last_str = rec.get("last_deploy_date")
    if not last_str:
        return {"in_cooldown": False, "days_remaining": 0,
                "last_deploy_date": None, "last_tier": rec.get("last_tier")}
    try:
        last = datetime.strptime(last_str, "%Y-%m-%d").date()
    except Exception:
        return {"in_cooldown": False, "days_remaining": 0,
                "last_deploy_date": last_str, "last_tier": rec.get("last_tier")}
    today = datetime.now(TIMEZONE_TW_MARKET).date()
    elapsed = (today - last).days
    days_remaining = max(0, TWSTOCK_MIN_DAYS_BETWEEN_DEPLOYMENTS - elapsed)
    return {
        "in_cooldown": days_remaining > 0,
        "days_remaining": days_remaining,
        "last_deploy_date": last_str,
        "last_tier": rec.get("last_tier"),
    }


# ============================
# 核心三級判定
# ============================

def _to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """日 K 重採樣為週 K(W = 週日結束;.last() 取每週最後一筆)。"""
    if df is None or df.empty:
        return pd.DataFrame()
    weekly = df.resample("W").last().dropna(how="all")
    return weekly


def _classify_core_tier(
    pct_from_high: Optional[float],
    weekly_rsi: Optional[float],
    vix: Optional[float],
) -> Optional[str]:
    """v4 三級判定。回 'A' / 'B' / 'C' / None。
    優先級 C > B > A(條件嚴的優先)。
    """
    if pct_from_high is None or weekly_rsi is None:
        return None

    rules = TWSTOCK_TIER_RULES
    # C 級:同時滿足 -30% / RSI<30 / VIX>35
    if (pct_from_high <= rules["C"]["drawdown_pct"]
            and weekly_rsi < rules["C"]["weekly_rsi_max"]
            and vix is not None and vix > rules["C"]["vix_min"]):
        return "C"
    # B 級
    if (pct_from_high <= rules["B"]["drawdown_pct"]
            and weekly_rsi < rules["B"]["weekly_rsi_max"]):
        return "B"
    # A 級
    if (pct_from_high <= rules["A"]["drawdown_pct"]
            and weekly_rsi < rules["A"]["weekly_rsi_max"]):
        return "A"
    return None


_TIER_META = {
    "A": {"action": "預備子彈 25% 加碼", "alert_level": "green"},
    "B": {"action": "預備子彈 35% 加碼", "alert_level": "yellow"},
    "C": {"action": "預備子彈 40% 加碼(VIX 極端)", "alert_level": "red"},
}


def _evaluate_core(symbol: str, name: str) -> dict:
    """共用核心三級評估邏輯。"""
    base = {
        "symbol": symbol,
        "name": name,
        "timestamp": datetime.now(TIMEZONE_TW_MARKET).isoformat(),
    }
    try:
        df = fetch_tw_history(symbol, period="2y")
        metrics = get_tw_52w_metrics(symbol)
    except Exception as e:
        logger.error(f"_evaluate_core({symbol}) data fetch failed: {e}")
        return {**base, "tier": None, "action": "no_data", "alert_level": "none",
                "error": str(e)}

    pct_from_high = metrics.get("pct_from_high")
    current = metrics.get("current")
    if df is None or df.empty or pct_from_high is None or current is None:
        return {**base, "tier": None, "action": "no_data", "alert_level": "none"}

    weekly = _to_weekly(df)
    weekly_rsi = get_rsi_latest(weekly, length=14) if not weekly.empty else None

    try:
        vix = fetch_vix_term_structure().get("vix")
    except Exception as e:
        logger.warning(f"VIX fetch failed: {e}")
        vix = None

    tier = _classify_core_tier(pct_from_high, weekly_rsi, vix)

    payload = {
        **base,
        "price": float(current),
        "pct_from_52w_high": float(pct_from_high),
        "rsi14_weekly": float(weekly_rsi) if weekly_rsi is not None else None,
        "vix": float(vix) if vix is not None else None,
        "tier": tier,
    }

    if tier is None:
        payload.update({"action": "觀望", "alert_level": "none",
                        "deploy_pct": None, "cooldown": False})
        return payload

    cd = get_cooldown_status(symbol)
    meta = _TIER_META[tier]
    deploy_pct = TWSTOCK_TIER_RULES[tier]["deploy_pct"]
    alert_level = "white" if cd["in_cooldown"] else meta["alert_level"]
    action = meta["action"] + (
        f"(冷卻中,還需 {cd['days_remaining']} 天)" if cd["in_cooldown"] else ""
    )

    payload.update({
        "action": action,
        "alert_level": alert_level,
        "deploy_pct": deploy_pct,
        "cooldown": cd["in_cooldown"],
        "cooldown_days_remaining": cd["days_remaining"],
    })
    return payload


def evaluate_00631l_signal() -> dict:
    """元大台灣 50 正 2(00631L)三級加碼訊號。"""
    try:
        return _evaluate_core("00631L.TW", "元大台灣 50 正 2")
    except Exception as e:
        logger.error(f"evaluate_00631l_signal failed: {e}")
        return {"symbol": "00631L.TW", "tier": None, "action": "error",
                "alert_level": "none", "error": str(e)}


def evaluate_2330_signal() -> dict:
    """台積電(2330)三級加碼訊號(同核心級別)。"""
    try:
        return _evaluate_core("2330.TW", "台積電")
    except Exception as e:
        logger.error(f"evaluate_2330_signal failed: {e}")
        return {"symbol": "2330.TW", "tier": None, "action": "error",
                "alert_level": "none", "error": str(e)}


def scan_twstock_core() -> list:
    """掃描台股核心(00631L + 2330)。"""
    return [evaluate_00631l_signal(), evaluate_2330_signal()]
