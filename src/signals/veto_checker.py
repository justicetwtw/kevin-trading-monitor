"""跨訊號通用否決(學習鎖)檢查。

實作 v4 真實 6 條學習鎖(全部從 src/config/thresholds.py HARD_RULES 讀,絕不 hardcode)
+ 3 條 Batch 8 依賴的 stub(L2 covered call / L5 hedge DTE / L6 drawdown);
stub 在 context=None 時 pass(視同 covered / 無 hedge 資料 / 無 drawdown 資料),
Batch 8 接入 management 模組後改為「依 context 判斷」。

公開介面:
- check_lock_*  各鎖獨立函式,回傳 (passed: bool, reason: str)
- check_all_hard_rules(signal_type, symbol, ...)  統一彙整,回傳所有失敗的 (False, reason)
"""

from loguru import logger

from src.config.thresholds import HARD_RULES
from src.config.universe import ETF_LEVERAGED_SINGLE_STOCK
from src.data.earnings_calendar import is_earnings_within_days
from src.data.vix_structure import is_vix_consecutive_above


# ============================
# v4 真實學習鎖(從 HARD_RULES 讀)
# ============================

def check_lock_min_leaps_dte(signal_type: str, dte_days: int | None) -> tuple[bool, str]:
    """LEAPS Long Call DTE 必須 >= 365(HARD_RULES.min_long_call_dte_days)。"""
    if signal_type != "leaps_entry" or dte_days is None:
        return True, "n/a"
    min_dte = HARD_RULES["min_long_call_dte_days"]
    if dte_days < min_dte:
        return False, f"v4_lock_dte_{dte_days}_below_{min_dte}"
    return True, "ok"


def check_lock_min_ivr_short_premium(signal_type: str, ivr: float | None) -> tuple[bool, str]:
    """賣 CALL / 賣 PUT 必須 IVR >= 30(HARD_RULES.min_ivr_for_short_premium)。"""
    if signal_type not in ("sell_call", "sell_put") or ivr is None:
        return True, "n/a"
    min_ivr = HARD_RULES["min_ivr_for_short_premium"]
    if ivr < min_ivr:
        return False, f"v4_lock_ivr_{ivr:.0f}_below_{min_ivr}"
    return True, "ok"


def check_lock_earnings_blackout(symbol: str, signal_type: str) -> tuple[bool, str]:
    """財報前 N 天禁開新短倉(HARD_RULES.no_short_premium_within_earnings_days)。"""
    if signal_type not in ("sell_call", "sell_put"):
        return True, "n/a"
    days = HARD_RULES["no_short_premium_within_earnings_days"]
    try:
        if is_earnings_within_days(symbol, days):
            return False, f"v4_lock_earnings_within_{days}_days"
    except Exception as e:
        logger.warning(f"earnings_blackout check failed (assume pass): {e}")
        return True, "earnings_check_failed_assume_ok"
    return True, "ok"


def check_lock_vix_consecutive(signal_type: str) -> tuple[bool, str]:
    """VIX 連 N 天 > 30 禁開新 LEAPS(HARD_RULES.no_long_premium_after_vix_high_days)。"""
    if signal_type != "leaps_entry":
        return True, "n/a"
    days = HARD_RULES["no_long_premium_after_vix_high_days"]
    try:
        if is_vix_consecutive_above(30, days):
            return False, f"v4_lock_vix_consecutive_above_30_for_{days}_days"
    except Exception as e:
        logger.warning(f"vix_consecutive check failed (assume pass): {e}")
        return True, "vix_check_failed_assume_ok"
    return True, "ok"


def check_lock_tier_c_no_sell_put(symbol: str, signal_type: str) -> tuple[bool, str]:
    """Tier C 標的不賣 PUT(HARD_RULES.tier_c_no_sell_put)。"""
    if signal_type != "sell_put":
        return True, "n/a"
    tier_c = HARD_RULES["tier_c_no_sell_put"]
    if symbol in tier_c:
        return False, f"v4_lock_tier_c_{symbol}_no_sell_put"
    return True, "ok"


def check_lock_2x_etf_no_leaps(symbol: str, signal_type: str) -> tuple[bool, str]:
    """單股 2x ETF 不開 LEAPS(HARD_RULES.no_long_position_for_2x_single_etf)。"""
    if signal_type != "leaps_entry":
        return True, "n/a"
    if not HARD_RULES.get("no_long_position_for_2x_single_etf", True):
        return True, "rule_disabled"
    if symbol in ETF_LEVERAGED_SINGLE_STOCK:
        return False, f"v4_lock_2x_etf_{symbol}_no_leaps"
    return True, "ok"


# ============================
# Batch 8 依賴 stub(context=None → pass)
# ============================

def check_lock_no_naked_call(symbol: str, context: dict | None = None) -> tuple[bool, str]:
    """L2 賣 CALL 必須 covered。Batch 7 stub:無 context 視同 covered。
    Batch 8 接入 current_positions 後,context["covered_by"] ∈ {"LEAPS", "shares", None}。
    """
    if context is None:
        return True, "stub_pre_batch8_assume_covered"
    covered_by = context.get("covered_by")
    if covered_by in ("LEAPS", "shares"):
        return True, f"covered_by_{covered_by}"
    return False, f"lock2_naked_call_{symbol}_no_cover"


def check_lock_hedge_dte(signal_type: str, context: dict | None = None) -> tuple[bool, str]:
    """L5 對沖 DTE < 45 → 擋新短倉(sell_call / sell_put)。Batch 7 stub:無 context pass。
    Batch 8 接入 hedge_dte_tracker 後,context["hedge_dte_days"]: int。
    """
    if signal_type not in ("sell_call", "sell_put"):
        return True, "n/a"
    if context is None:
        return True, "stub_pre_batch8_no_hedge_dte_check"
    dte = context.get("hedge_dte_days")
    if dte is None:
        return True, "no_hedge_dte_provided"
    if dte < 45:
        return False, f"lock5_hedge_dte_{dte}_below_45"
    return True, "ok"


def check_lock_drawdown(signal_type: str, context: dict | None = None) -> tuple[bool, str]:
    """L6 帳戶回撤 <= -20% → 擋新 LEAPS。Batch 7 stub:無 context pass。
    Batch 8 接入 account_drawdown 後,context["drawdown_pct"]: float(負數)。
    """
    if signal_type != "leaps_entry":
        return True, "n/a"
    if context is None:
        return True, "stub_pre_batch8_no_drawdown_check"
    drawdown = context.get("drawdown_pct")
    if drawdown is None:
        return True, "no_drawdown_provided"
    if drawdown <= -0.20:
        return False, f"lock6_drawdown_{drawdown * 100:.1f}pct_at_or_below_-20pct"
    return True, "ok"


# ============================
# 統一彙整
# ============================

def check_all_hard_rules(
    signal_type: str,
    symbol: str,
    dte_days: int | None = None,
    ivr: float | None = None,
    context: dict | None = None,
) -> list[tuple[bool, str]]:
    """跑全部學習鎖。回傳 list of (passed=False, reason),空 list 代表全 pass。

    參數:
        signal_type: "sell_call" | "sell_put" | "leaps_entry"
        symbol: ticker
        dte_days: LEAPS 進場時的 days-to-expiry(其他訊號類型忽略)
        ivr: IV Rank(0-100),sell_call/sell_put 用
        context: Batch 8 注入的部位 / 對沖 / drawdown 資料(目前 stub)

    返回:
        [(False, reason1), (False, reason2), ...] — 空 list = 全 pass
    """
    checks = [
        check_lock_min_leaps_dte(signal_type, dte_days),
        check_lock_min_ivr_short_premium(signal_type, ivr),
        check_lock_earnings_blackout(symbol, signal_type),
        check_lock_vix_consecutive(signal_type),
        check_lock_tier_c_no_sell_put(symbol, signal_type),
        check_lock_2x_etf_no_leaps(symbol, signal_type),
        check_lock_no_naked_call(symbol, context if signal_type == "sell_call" else None),
        check_lock_hedge_dte(signal_type, context),
        check_lock_drawdown(signal_type, context),
    ]
    return [(ok, reason) for ok, reason in checks if not ok]
