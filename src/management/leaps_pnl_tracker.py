"""LEAPS PnL triggers: +50 / +100 / -30 / -40 / DTE low."""

from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from src.config.thresholds import LEAPS_MANAGEMENT_TRIGGERS
from src.data.greeks_calculator import calc_bs_price
from src.data.iv_rank import get_atm_iv
from src.data.price_data import get_latest_price
from src.management.current_positions import get_long_options


def calc_option_pnl(option: dict) -> dict:
    """Estimate one LEAPS position and return per-contract PnL.

    `calc_bs_price` returns premium per share. Position schema stores
    `cost_per_contract` as premium per share × 100, so both values must be
    converted to the same per-contract unit before calculating PnL.
    """
    symbol = option["symbol"]
    underlying = get_latest_price(symbol)
    if underlying is None:
        return {}

    implied_volatility: Optional[float] = get_atm_iv(symbol) or 0.30
    expiry = datetime.strptime(option["expiry"], "%Y-%m-%d").replace(
        tzinfo=timezone.utc
    )
    dte = (expiry.date() - datetime.now(timezone.utc).date()).days
    if dte <= 0:
        return {"option_id": option.get("id"), "expired": True}

    per_share = calc_bs_price(
        S=float(underlying),
        K=float(option["strike"]),
        T=dte / 365,
        r=0.045,
        sigma=float(implied_volatility),
        option_type="call" if option["type"] == "long_call" else "put",
    )
    current_per_contract = float(per_share) * 100
    cost_per_contract = float(option["cost_per_contract"])
    pnl_pct = (
        (current_per_contract - cost_per_contract) / cost_per_contract
        if cost_per_contract
        else 0.0
    )

    return {
        "option_id": option.get("id"),
        "underlying": float(underlying),
        "current_price_per_contract": round(current_per_contract, 2),
        "cost_per_contract": cost_per_contract,
        "pnl_pct": round(pnl_pct, 4),
        "dte": dte,
    }


def scan_all_leaps() -> list:
    """Check all long options against management triggers."""
    triggers = []
    rules = LEAPS_MANAGEMENT_TRIGGERS

    for option in get_long_options():
        try:
            pnl = calc_option_pnl(option)
            if not pnl or pnl.get("expired"):
                continue
            pct = pnl["pnl_pct"]
            dte = pnl["dte"]

            if pct >= rules["profit_take_partial_pct"]:
                triggers.append({
                    "option_id": option.get("id"),
                    "level": "+100",
                    "action": "賣 1/3 鎖利",
                    "pnl": pnl,
                })
            elif pct >= rules["profit_protect_pct"]:
                triggers.append({
                    "option_id": option.get("id"),
                    "level": "+50",
                    "action": "考慮變 diagonal",
                    "pnl": pnl,
                })
            elif pct <= rules["loss_force_decision_pct"]:
                triggers.append({
                    "option_id": option.get("id"),
                    "level": "-40",
                    "action": "強制決策:roll/平/diagonal",
                    "pnl": pnl,
                })
            elif pct <= rules["loss_warning_pct"]:
                triggers.append({
                    "option_id": option.get("id"),
                    "level": "-30",
                    "action": "警告,評估",
                    "pnl": pnl,
                })

            if dte < rules["dte_roll_threshold_days"]:
                triggers.append({
                    "option_id": option.get("id"),
                    "level": "DTE_low",
                    "action": "評估 roll out 至 18+ 月",
                    "dte": dte,
                })
        except Exception as exc:
            logger.error(f"scan_all_leaps({option.get('id')}) failed: {exc}")
    return triggers


check_leaps_triggers = scan_all_leaps
