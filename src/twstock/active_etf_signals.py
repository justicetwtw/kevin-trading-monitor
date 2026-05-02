"""主動 ETF 三級訊號(v4 邏輯,跨 ETF 共識聚合)。

對應 TWSTOCK_ACTIVE_ETF_RULES:
  🟡 Tier 1:單一 ETF 加碼某股 ≥ 1 pp(weight diff)            → 記錄
  🟠 Tier 2:7 天內 ≥ 3 檔 ETF 同方向加碼同一股                 → 推播
  🔴 Tier 3:30 天 ≥ 5 檔共識集體增權重                          → 最高優先

注意:`tier1_single_etf_min_nav_pct` 雖鍵名 _pct,值是百分點(1.0 = 1%)。
PHASE_2_NOTES 已記錄重命名為 _diff_pp(post-Phase 2 重構)。
"""

from datetime import datetime
from typing import Optional

from loguru import logger

from src.config.settings import TIMEZONE_TW_MARKET
from src.config.thresholds import TWSTOCK_ACTIVE_ETF_RULES
from src.config.universe import TWSTOCK_ACTIVE_ETFS
from src.data.twstock_active_etf import aggregate_cross_etf_signals


_TIER_META = {
    1: {"action": "單檔主動 ETF 加碼,記錄觀察", "alert_level": "yellow"},
    2: {"action": "多檔主動 ETF 7 日內共識加碼,推播", "alert_level": "orange"},
    3: {"action": "≥5 檔主動 ETF 30 日集體增權重,最高優先", "alert_level": "red"},
}


def _max_diff(increased: list) -> Optional[float]:
    if not increased:
        return None
    try:
        return max(item["diff_pct"] for item in increased)
    except Exception:
        return None


def evaluate_active_etf(symbol: str) -> dict:
    """單一標的的主動 ETF 三級訊號。

    symbol 是「被持有的個股」(非 ETF 本身),例如 "2330" / "2454" / "3008"。
    """
    base = {
        "symbol": symbol,
        "timestamp": datetime.now(TIMEZONE_TW_MARKET).isoformat(),
    }
    rules = TWSTOCK_ACTIVE_ETF_RULES
    tier1_pp = rules.get("tier1_single_etf_min_nav_pct", 1.0)  # 單位:百分點
    tier2_count = rules.get("tier2_multi_etf_count", 3)
    tier2_lookback = rules.get("tier2_lookback_days", 7)
    tier3_count = rules.get("tier3_consensus_etf_count", 5)
    tier3_lookback = rules.get("tier3_lookback_days", 30)

    try:
        agg_short = aggregate_cross_etf_signals(lookback_days=tier2_lookback)
        agg_long = aggregate_cross_etf_signals(lookback_days=tier3_lookback)
    except Exception as e:
        logger.error(f"aggregate_cross_etf_signals failed: {e}")
        return {**base, "tier": None, "action": "no_data", "alert_level": "none",
                "error": str(e)}

    short_entry = agg_short.get(symbol, {}) if isinstance(agg_short, dict) else {}
    long_entry = agg_long.get(symbol, {}) if isinstance(agg_long, dict) else {}
    short_inc = short_entry.get("increased_etfs", [])
    long_inc = long_entry.get("increased_etfs", [])

    n_short = len(short_inc)
    n_long = len(long_inc)
    max_short_diff = _max_diff(short_inc)

    # 優先級:Tier 3 > Tier 2 > Tier 1(條件越嚴越優先)
    tier: Optional[int] = None
    if n_long >= tier3_count:
        tier = 3
    elif n_short >= tier2_count:
        tier = 2
    elif max_short_diff is not None and max_short_diff >= tier1_pp:
        tier = 1

    payload = {
        **base,
        "tier": tier,
        "n_etfs_increased_short_window": n_short,
        "n_etfs_increased_long_window": n_long,
        "max_diff_pp_short_window": max_short_diff,
        "increased_etfs_short_window": short_inc,
        "increased_etfs_long_window": long_inc,
    }

    if tier is None:
        if n_short == 0 and n_long == 0:
            payload.update({"action": "no_data", "alert_level": "none"})
        else:
            payload.update({"action": "未達加碼門檻", "alert_level": "none"})
        return payload

    meta = _TIER_META[tier]
    payload.update({"action": meta["action"], "alert_level": meta["alert_level"]})
    return payload


def scan_all_active_etfs() -> list:
    """掃 universe 內被主動 ETF 持有的所有個股。

    universe 來源:把所有主動 ETF 短窗增持的 symbols 聚合起來,
    讓 evaluate_active_etf 對「曾被加碼過的個股」逐一判定。
    冷啟動 / 資料不存在 → 仍至少回傳一個 placeholder dict 方便 debug。
    """
    rules = TWSTOCK_ACTIVE_ETF_RULES
    short_lb = rules.get("tier2_lookback_days", 7)
    long_lb = rules.get("tier3_lookback_days", 30)

    try:
        agg_short = aggregate_cross_etf_signals(lookback_days=short_lb)
        agg_long = aggregate_cross_etf_signals(lookback_days=long_lb)
    except Exception as e:
        logger.warning(f"scan_all_active_etfs aggregate failed: {e}")
        agg_short, agg_long = {}, {}

    syms = set()
    for agg in (agg_short, agg_long):
        if isinstance(agg, dict):
            syms.update(agg.keys())

    if not syms:
        # 冷啟動:資料源沒任何 symbol,回 universe 摘要 placeholder
        logger.info("scan_all_active_etfs: no holdings data, returning placeholder")
        return [{
            "symbol": "_universe",
            "tier": None,
            "action": "no_data",
            "alert_level": "none",
            "n_active_etfs": len(TWSTOCK_ACTIVE_ETFS),
            "timestamp": datetime.now(TIMEZONE_TW_MARKET).isoformat(),
        }]

    return [evaluate_active_etf(sym) for sym in sorted(syms)]
