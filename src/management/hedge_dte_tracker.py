"""對沖部位 DTE < 45 天提醒 + 純讀介面。

主名:scan_all_hedges()
別名:check_hedge_dte = scan_all_hedges
純讀:get_min_hedge_dte() — 給 veto_checker context。
"""

from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from src.config.thresholds import HEDGE_DTE_THRESHOLD_DAYS
from src.config.universe import ETF_HEDGE
from src.management.current_positions import get_long_options


def _is_hedge(opt: dict) -> bool:
    """對沖認定:大盤 hedge ETF 的任何 long option,或任何 long_put。"""
    return opt.get("symbol") in ETF_HEDGE or opt.get("type") == "long_put"


def _dte_of(opt: dict) -> Optional[int]:
    expiry_str = opt.get("expiry")
    if not expiry_str:
        return None
    try:
        expiry = datetime.strptime(expiry_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return (expiry.date() - datetime.now(timezone.utc).date()).days
    except Exception:
        return None


def scan_all_hedges() -> list:
    """檢查對沖部位(long put / hedge ETF long option)DTE。冷啟動 → []。"""
    alerts = []
    for opt in get_long_options():
        if not _is_hedge(opt):
            continue
        try:
            dte = _dte_of(opt)
            if dte is None:
                continue
            if 0 < dte < HEDGE_DTE_THRESHOLD_DAYS:
                alerts.append({
                    "option_id": opt.get("id"),
                    "symbol": opt.get("symbol"), "dte": dte,
                    "action": "對沖即將進入加速耗損期,建議換倉",
                })
        except Exception as e:
            logger.error(f"scan_all_hedges({opt}) failed: {e}")
    return alerts


def get_min_hedge_dte() -> Optional[int]:
    """所有對沖部位中最小 DTE。無 hedge / 冷啟動 → None。"""
    dtes = []
    for opt in get_long_options():
        if not _is_hedge(opt):
            continue
        d = _dte_of(opt)
        if d is not None and d > 0:
            dtes.append(d)
    return min(dtes) if dtes else None


check_hedge_dte = scan_all_hedges
