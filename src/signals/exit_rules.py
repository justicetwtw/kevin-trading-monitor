"""5 大出場規則 + value_thesis 例外。雙介面。

evaluate_exit_rules_for_symbol(symbol, leaps_dte=None) -> list[dict]   # per-symbol
evaluate_all_exit_rules() -> list[dict]                                  # iterate positions
冷啟動沒 positions → 回 [],絕不崩。
"""

from datetime import datetime, timezone

from loguru import logger

from src.config.thresholds import SEASONAL_EXIT_RULES
from src.data.analyst_actions import has_recent_downgrades
from src.data.fundamentals import detect_consecutive_eps_miss
from src.data.price_data import fetch_history, get_52w_high_low
from src.indicators.basic import get_rsi_latest, get_bbands_position, get_ma_position
from src.signals.leaps_entry_scorer import get_value_thesis


def _now_local() -> datetime:
    """季節性規則需要月份判斷;統一用 UTC(月份不會跨日界線變)。"""
    return datetime.now(timezone.utc)


def rule_a_technical_exit(symbol: str) -> dict:
    """規則 A:進場理由消失(RSI>75 + BB上軌 + 距 50MA +10% + 距 52W 高 -3% 內)。"""
    try:
        df = fetch_history(symbol, period="3mo", interval="1d")
        if df is None or df.empty:
            return {"rule": "A_technical_exit", "trigger": False, "reason": "no_data"}

        rsi = get_rsi_latest(df) or 50
        bb = get_bbands_position(df) or {}
        ma = get_ma_position(df) or {}
        high = get_52w_high_low(symbol) or {}

        triggers = []
        if rsi > 75:
            triggers.append("rsi_above_75")
        if bb.get("touch_upper") or (bb.get("pct", 0.5) > 0.95):
            triggers.append("bb_upper_break")
        if ma.get("pct_from_sma_50", 0) > 0.10:
            triggers.append("above_50ma_10pct")
        pct_from_high = high.get("pct_from_high")
        if pct_from_high is not None and pct_from_high > -0.03:
            triggers.append("near_52w_high_3pct")

        thesis = get_value_thesis(symbol)
        note = ("value_thesis=deep_value → 改出戰術賣 short call,不出場"
                if thesis == "deep_value" else None)

        return {
            "rule": "A_technical_exit",
            "symbol": symbol,
            "trigger": len(triggers) >= 2,
            "triggers": triggers,
            "value_thesis": thesis,
            "note": note,
        }
    except Exception as e:
        logger.warning(f"rule_a_technical_exit({symbol}) failed: {e}")
        return {"rule": "A_technical_exit", "symbol": symbol, "trigger": False,
                "error": str(e)}


def rule_b_fundamental_breakdown(symbol: str) -> dict:
    """規則 B:基本面破裂(連 2 季 EPS miss + 3 家分析師下調)。"""
    try:
        eps_miss = detect_consecutive_eps_miss(symbol, 2)
        downgrades = has_recent_downgrades(symbol, n_min=3, lookback_days=30)
        triggered = bool(eps_miss or downgrades)
        return {
            "rule": "B_fundamental_breakdown",
            "symbol": symbol,
            "trigger": triggered,
            "eps_miss": bool(eps_miss),
            "downgrades": bool(downgrades),
            "action": "value_thesis 重新評估" if triggered else None,
        }
    except Exception as e:
        logger.warning(f"rule_b_fundamental_breakdown({symbol}) failed: {e}")
        return {"rule": "B_fundamental_breakdown", "symbol": symbol,
                "trigger": False, "error": str(e)}


def rule_c_seasonal_year_end(symbol: str, dte: int = 90) -> dict:
    """規則 C:LEAPS 季節性最佳化(11-12 月、DTE 60-120、距高點 < 5%)。"""
    try:
        rules = SEASONAL_EXIT_RULES.get("leaps_year_end_peak", {})
        if not rules:
            return {"rule": "C_seasonal_year_end", "symbol": symbol,
                    "trigger": False, "reason": "rules_missing"}

        now = _now_local()
        in_window = now.month in rules["trigger_months"]
        dte_lo, dte_hi = rules["dte_range_days"]
        dte_ok = dte_lo <= dte <= dte_hi

        high = get_52w_high_low(symbol) or {}
        pct_from_high = high.get("pct_from_high")
        near_high = (
            pct_from_high is not None
            and pct_from_high > -rules["near_high_pct"]
        )

        triggered = bool(in_window and dte_ok and near_high)
        thesis = get_value_thesis(symbol)
        note = ("value_thesis=deep_value → 降為 roll out 建議"
                if (thesis == "deep_value" and triggered) else None)

        return {
            "rule": "C_seasonal_year_end",
            "symbol": symbol,
            "trigger": triggered,
            "in_window": in_window,
            "dte_ok": dte_ok,
            "near_high": near_high,
            "value_thesis": thesis,
            "note": note,
        }
    except Exception as e:
        logger.warning(f"rule_c_seasonal_year_end({symbol}) failed: {e}")
        return {"rule": "C_seasonal_year_end", "symbol": symbol,
                "trigger": False, "error": str(e)}


def rule_e_september_slump(symbol: str) -> dict:
    """規則 E:September Slump 防禦(7 月底-8 月中、週 RSI > 70、距高點 < 3%)。"""
    try:
        rules = SEASONAL_EXIT_RULES.get("september_slump_defense", {})
        if not rules:
            return {"rule": "E_september_slump", "symbol": symbol,
                    "trigger": False, "reason": "rules_missing"}

        now = _now_local()
        in_window = now.month in rules["trigger_months"]

        df = fetch_history(symbol, period="3mo", interval="1wk")
        if df is None or df.empty:
            return {"rule": "E_september_slump", "symbol": symbol,
                    "trigger": False, "reason": "no_data"}

        weekly_rsi = get_rsi_latest(df, 14) or 50
        high = get_52w_high_low(symbol) or {}
        pct_from_high = high.get("pct_from_high")
        near_high = (
            pct_from_high is not None
            and pct_from_high > -rules["near_high_pct"]
        )

        triggered = bool(in_window and weekly_rsi >= rules["weekly_rsi_min"] and near_high)

        thesis = get_value_thesis(symbol)
        if triggered and thesis == "deep_value":
            return {"rule": "E_september_slump", "symbol": symbol,
                    "trigger": False, "note": "value_thesis=deep_value 跳過"}

        return {
            "rule": "E_september_slump",
            "symbol": symbol,
            "trigger": triggered,
            "weekly_rsi": float(weekly_rsi),
            "in_window": in_window,
            "action": (
                f"建議減碼 {rules['reduce_position_pct']:.0%}" if triggered else None
            ),
        }
    except Exception as e:
        logger.warning(f"rule_e_september_slump({symbol}) failed: {e}")
        return {"rule": "E_september_slump", "symbol": symbol,
                "trigger": False, "error": str(e)}


def evaluate_exit_rules_for_symbol(symbol: str, leaps_dte: int | None = None) -> list[dict]:
    """per-symbol 跑 4 條規則(A / B / E 一律跑;C 僅在 leaps_dte 提供時跑)。"""
    triggered = []
    for fn in (rule_a_technical_exit, rule_b_fundamental_breakdown, rule_e_september_slump):
        try:
            r = fn(symbol)
            if r.get("trigger"):
                triggered.append(r)
        except Exception as e:
            logger.error(f"{fn.__name__}({symbol}) failed: {e}")

    if leaps_dte is not None:
        try:
            r = rule_c_seasonal_year_end(symbol, leaps_dte)
            if r.get("trigger"):
                triggered.append(r)
        except Exception as e:
            logger.error(f"rule_c_seasonal_year_end({symbol}) failed: {e}")

    return triggered


def evaluate_all_exit_rules() -> list[dict]:
    """iterate positions wrapper。Batch 8 才有 current_positions,現在 import 失敗 → 回 []。"""
    try:
        from src.management.current_positions import load_positions  # noqa: F401  (Batch 8)
    except ImportError:
        logger.info("evaluate_all_exit_rules: current_positions not yet (Batch 8) → return []")
        return []

    try:
        positions = load_positions() or {}
    except Exception as e:
        logger.warning(f"load_positions failed: {e}")
        return []

    out: list[dict] = []
    stocks = positions.get("stocks") or []
    options = positions.get("options") or []

    for p in stocks:
        sym = p.get("symbol") if isinstance(p, dict) else None
        if not sym:
            continue
        out.extend(evaluate_exit_rules_for_symbol(sym))

    for p in options:
        sym = p.get("symbol") if isinstance(p, dict) else None
        if not sym:
            continue
        dte = p.get("dte_days") if isinstance(p, dict) else None
        out.extend(evaluate_exit_rules_for_symbol(sym, leaps_dte=dte))

    return out
