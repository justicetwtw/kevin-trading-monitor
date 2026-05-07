"""跨訊號通用否決(學習鎖)檢查。

實作 v4 真實 6 條 + Batch 8 三條從 management 讀資料的學習鎖
(L2 covered call / L5 hedge DTE / L6 drawdown)。
全部閾值從 src/config/thresholds.py HARD_RULES 讀,絕不 hardcode。

公開介面:
- check_lock_*  各鎖獨立函式,回傳 (passed: bool, reason: str)
- check_all_hard_rules(signal_type, symbol, ...)  統一彙整,回傳所有失敗的 (False, reason)
"""

from loguru import logger

from src.config.thresholds import HARD_RULES, EARNINGS_BLACKOUT_DAYS_BY_THESIS
from src.data.value_thesis import get_value_thesis
from src.config.universe import ETF_LEVERAGED_SINGLE_STOCK, is_etf_symbol
from src.data.earnings_calendar import is_earnings_within_days
from src.data.vix_structure import is_vix_consecutive_above
from src.management.account_drawdown import get_current_drawdown
from src.management.current_positions import load_positions
from src.management.hedge_dte_tracker import get_min_hedge_dte


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


def check_lock_min_ivr_short_premium(
    signal_type: str, ivr: float | None, symbol: str | None = None,
) -> tuple[bool, str]:
    """賣 CALL / 賣 PUT 必須 IVR 達標(v4.1:個股 70 / ETF 30)。

    v4.1 學習鎖第 2 條分流:
    - 個股(非 ETF):min_ivr_for_short_premium_stock = 70
    - ETF / 2x ETF: min_ivr_for_short_premium_etf = 30

    symbol 參數選填,缺省時 fallback 到 v4 遺留的 min_ivr_for_short_premium = 30
    (向下相容)。
    """
    if signal_type not in ("sell_call", "sell_put") or ivr is None:
        return True, "n/a"
    if symbol is None:
        # v4 fallback(向下相容)
        min_ivr = HARD_RULES["min_ivr_for_short_premium"]
        asset_tag = "v4_legacy"
    elif is_etf_symbol(symbol):
        min_ivr = HARD_RULES["min_ivr_for_short_premium_etf"]
        asset_tag = "etf"
    else:
        min_ivr = HARD_RULES["min_ivr_for_short_premium_stock"]
        asset_tag = "stock"
    if ivr < min_ivr:
        return False, f"v41_lock_ivr_{asset_tag}_{ivr:.0f}_below_{min_ivr}"
    return True, "ok"


def check_lock_earnings_blackout(symbol: str, signal_type: str) -> tuple[bool, str]:
    """財報前 N 天禁開新短倉(v4.1:依 value_thesis 動態)。

    v4.1 學習鎖第 3 條 × value_thesis 分流:
    - deep_value / fair_value: 1 天前禁(激進吃 IV 高峰)
    - expensive: 7 天前禁(保守,因可能拉回)
    - review / exit: 全期間禁(365 天模擬永久)

    fallback:thesis 讀失敗回 fair_value (1 天)。HARD_RULES["no_short_premium_within_earnings_days"]
    保留為 v4 遺留(向下相容,目前不再用)。
    """
    if signal_type not in ("sell_call", "sell_put"):
        return True, "n/a"
    thesis = get_value_thesis(symbol)
    days = EARNINGS_BLACKOUT_DAYS_BY_THESIS.get(thesis, 1)
    try:
        if is_earnings_within_days(symbol, days):
            return False, f"v41_lock_earnings_{thesis}_within_{days}_days"
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
    """單股 2x ETF 不開 LEAPS(HARD_RULES.no_long_position_for_2x_single_etf)。

    v4.1 註解:LEAPS 對 underlying 個股開,不對 2x ETF 開。此 check 維持原行為,
    向下相容。v4.1 真正的反向意義(持現股 + 不賣 covered call)由
    check_lock_2x_etf_no_short_call 實作。
    """
    if signal_type != "leaps_entry":
        return True, "n/a"
    if not HARD_RULES.get("no_long_position_for_2x_single_etf", True):
        return True, "rule_disabled"
    if symbol in ETF_LEVERAGED_SINGLE_STOCK:
        return False, f"v4_lock_2x_etf_{symbol}_no_leaps"
    return True, "ok"


def check_lock_2x_etf_no_short_call(symbol: str, signal_type: str) -> tuple[bool, str]:
    """單股 2x ETF 不賣 covered call(HARD_RULES.no_short_call_for_2x_single_etf)。

    v4.1 學習鎖第 6 條反向後新增:單股 2x ETF 持現股波段操作 OK,但選擇權流動性差,
    不適合賣 covered call。僅對 sell_call 訊號生效。
    """
    if signal_type != "sell_call":
        return True, "n/a"
    if not HARD_RULES.get("no_short_call_for_2x_single_etf", True):
        return True, "rule_disabled"
    if symbol in ETF_LEVERAGED_SINGLE_STOCK:
        return False, f"v41_lock_2x_etf_{symbol}_no_short_call"
    return True, "ok"


# ============================
# Batch 8 — 從 management 讀資料的學習鎖
# ============================

def check_lock_no_naked_call(
    signal_type: str,
    symbol: str,
    context: dict | None = None,
) -> tuple[bool, str]:
    """L2 賣 CALL 必須 covered(同標的有現股或 long_call)。
    HARD_RULES["require_covered_for_short_call"] = False 可整條停用。
    僅對 sell_call 生效。
    """
    if signal_type != "sell_call":
        return True, "n/a"
    if not HARD_RULES.get("require_covered_for_short_call", True):
        return True, "rule_disabled"

    # context["covered_by"] 顯式指定可短路(供呼叫端覆寫,例如 backtest)
    if context is not None:
        covered_by = context.get("covered_by")
        if covered_by in ("LEAPS", "shares"):
            return True, f"covered_by_{covered_by}"

    try:
        positions = load_positions() or {}
    except Exception as e:
        logger.warning(f"load_positions failed in lock2: {e} → assume pass")
        return True, "lock2_load_failed_assume_pass"

    has_shares = any(
        s.get("symbol") == symbol and not s.get("_example")
        for s in positions.get("stocks", []) or []
    )
    has_long_call = any(
        o.get("symbol") == symbol
        and o.get("type") == "long_call"
        and not o.get("_example")
        for o in positions.get("options", []) or []
    )
    if has_shares or has_long_call:
        return True, "covered"
    return False, f"lock2_naked_call_{symbol}_no_cover"


def check_lock_hedge_dte(signal_type: str, context: dict | None = None) -> tuple[bool, str]:
    """L5 對沖 DTE < HARD_RULES.min_hedge_dte_days → 擋新短倉(sell_call / sell_put)。
    無 hedge 部位 → pass(冷啟動安全)。
    """
    if signal_type not in ("sell_call", "sell_put"):
        return True, "n/a"

    # context override(若呼叫端已查過,避免重複讀檔)
    if context is not None and "hedge_dte_days" in context:
        dte = context.get("hedge_dte_days")
    else:
        try:
            dte = get_min_hedge_dte()
        except Exception as e:
            logger.warning(f"get_min_hedge_dte failed: {e} → assume pass")
            return True, "lock5_query_failed_assume_pass"

    if dte is None:
        return True, "no_hedge_position"
    threshold = HARD_RULES.get("min_hedge_dte_days", 45)
    if dte < threshold:
        return False, f"lock5_hedge_dte_{dte}_below_{threshold}"
    return True, "ok"


def check_lock_drawdown(signal_type: str, context: dict | None = None) -> tuple[bool, str]:
    """L6 帳戶回撤 <= HARD_RULES.max_drawdown_pct_for_new_leaps → 擋新 LEAPS。
    無 account 歷史 → pass(冷啟動安全)。
    """
    if signal_type != "leaps_entry":
        return True, "n/a"

    if context is not None and "drawdown_pct" in context:
        drawdown = context.get("drawdown_pct")
    else:
        try:
            drawdown = get_current_drawdown().get("drawdown_pct")
        except Exception as e:
            logger.warning(f"get_current_drawdown failed: {e} → assume pass")
            return True, "lock6_query_failed_assume_pass"

    if drawdown is None:
        return True, "no_account_value_history"
    threshold = HARD_RULES.get("max_drawdown_pct_for_new_leaps", -0.20)
    if drawdown <= threshold:
        return False, f"lock6_drawdown_{drawdown * 100:.1f}pct_at_or_below_{threshold * 100:.0f}pct"
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
        check_lock_min_ivr_short_premium(signal_type, ivr, symbol=symbol),
        check_lock_earnings_blackout(symbol, signal_type),
        check_lock_vix_consecutive(signal_type),
        check_lock_tier_c_no_sell_put(symbol, signal_type),
        check_lock_2x_etf_no_leaps(symbol, signal_type),
        check_lock_2x_etf_no_short_call(symbol, signal_type),
        check_lock_no_naked_call(signal_type, symbol, context),
        check_lock_hedge_dte(signal_type, context),
        check_lock_drawdown(signal_type, context),
    ]
    return [(ok, reason) for ok, reason in checks if not ok]
