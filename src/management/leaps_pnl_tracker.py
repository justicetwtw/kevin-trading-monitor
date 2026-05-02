"""LEAPS 損益觸發 - +50 / +100 / -30 / -40 / DTE_low。

主名:scan_all_leaps()
別名:check_leaps_triggers = scan_all_leaps
"""

from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from src.config.thresholds import LEAPS_MANAGEMENT_TRIGGERS
from src.data.greeks_calculator import calc_bs_price
from src.data.iv_rank import get_atm_iv
from src.data.price_data import get_latest_price
from src.management.current_positions import get_long_options


def calc_option_pnl(option: dict) -> dict:
    """單一 LEAPS 估值損益(以當前 ATM IV + B-S 估)。"""
    sym = option["symbol"]
    underlying = get_latest_price(sym)
    if underlying is None:
        return {}

    iv: Optional[float] = get_atm_iv(sym) or 0.30
    expiry = datetime.strptime(option["expiry"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    today = datetime.now(timezone.utc)
    dte = (expiry.date() - today.date()).days
    if dte <= 0:
        return {"option_id": option.get("id"), "expired": True}

    bs_type = "call" if option["type"] == "long_call" else "put"
    current_price = calc_bs_price(
        S=float(underlying), K=float(option["strike"]),
        T=dte / 365, r=0.045, sigma=float(iv), option_type=bs_type,
    )

    cost = float(option["cost_per_contract"])
    pnl_pct = (current_price - cost) / cost if cost else 0.0

    return {
        "option_id": option.get("id"),
        "underlying": float(underlying),
        "current_price_per_contract": round(current_price, 2),
        "cost_per_contract": cost,
        "pnl_pct": round(pnl_pct, 4),
        "dte": dte,
    }


def scan_all_leaps() -> list:
    """檢查所有 LEAPS 是否觸發管理規則。冷啟動無部位 → []。"""
    triggers = []
    rules = LEAPS_MANAGEMENT_TRIGGERS

    for opt in get_long_options():
        try:
            pnl = calc_option_pnl(opt)
            if not pnl or pnl.get("expired"):
                continue
            pct = pnl["pnl_pct"]
            dte = pnl["dte"]

            if pct >= rules["profit_take_partial_pct"]:
                triggers.append({"option_id": opt.get("id"), "level": "+100",
                                 "action": "賣 1/3 鎖利", "pnl": pnl})
            elif pct >= rules["profit_protect_pct"]:
                triggers.append({"option_id": opt.get("id"), "level": "+50",
                                 "action": "考慮變 diagonal", "pnl": pnl})
            elif pct <= rules["loss_force_decision_pct"]:
                triggers.append({"option_id": opt.get("id"), "level": "-40",
                                 "action": "強制決策:roll/平/diagonal", "pnl": pnl})
            elif pct <= rules["loss_warning_pct"]:
                triggers.append({"option_id": opt.get("id"), "level": "-30",
                                 "action": "警告,評估", "pnl": pnl})

            if dte < rules["dte_roll_threshold_days"]:
                triggers.append({"option_id": opt.get("id"), "level": "DTE_low",
                                 "action": "評估 roll out 至 18+ 月", "dte": dte})
        except Exception as e:
            logger.error(f"scan_all_leaps({opt.get('id')}) failed: {e}")
    return triggers


check_leaps_triggers = scan_all_leaps
