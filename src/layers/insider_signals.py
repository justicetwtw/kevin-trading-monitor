"""Layer F.4 - Insider Cluster Buying(per-signal modifier)

tier3 cluster:30 天 / >=3 位 insider P 代碼買入 / 總額 >= $500k → leaps +20、sell_put +15
tier2 ceo_cfo:7 天 / >= $250k → leaps +10
tier1 / none:0
所有閾值從 src/config/thresholds.py INSIDER_BUYING_RULES 讀,絕不 hardcode。
"""

from datetime import datetime, timezone

from loguru import logger

from src.config.thresholds import INSIDER_BUYING_RULES
from src.data.form4_insider import detect_cluster_buying, detect_ceo_cfo_buy
from src.storage.state_manager import write_json


def get_insider_modifier(symbol: str) -> dict:
    """根據 Cluster + CEO/CFO 大買加成。失敗冷啟動全 0。"""
    try:
        cluster = detect_cluster_buying(
            symbol,
            lookback_days=INSIDER_BUYING_RULES["tier3_cluster"]["lookback_days"],
            min_insiders=INSIDER_BUYING_RULES["tier3_cluster"]["min_insiders"],
            min_total_usd=INSIDER_BUYING_RULES["tier3_cluster"]["min_total_usd"],
        ) or {}
        ceo_buys = detect_ceo_cfo_buy(
            symbol,
            lookback_days=7,
            min_usd=INSIDER_BUYING_RULES["tier2_ceo_cfo_min_usd"],
        ) or []

        leaps_mod = 0
        sell_put_mod = 0
        tier = "none"

        if cluster.get("is_cluster"):
            leaps_mod = INSIDER_BUYING_RULES["tier3_signal_boost"]["leaps_entry"]
            sell_put_mod = INSIDER_BUYING_RULES["tier3_signal_boost"]["sell_put"]
            tier = "tier3_cluster"
        elif ceo_buys:
            leaps_mod = INSIDER_BUYING_RULES["tier2_signal_boost"]["leaps_entry"]
            tier = "tier2_ceo_cfo"

        return {
            "tier": tier,
            "cluster_data": cluster,
            "ceo_cfo_buys": ceo_buys,
            "modifiers": {
                "leaps_entry": int(leaps_mod),
                "sell_put": int(sell_put_mod),
            },
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.warning(f"get_insider_modifier({symbol}) failed (cold-start fallback): {e}")
        return {
            "tier": "cold_start",
            "cluster_data": {},
            "ceo_cfo_buys": [],
            "modifiers": {"leaps_entry": 0, "sell_put": 0},
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
        }


def build_insider_dashboard(symbols: list) -> dict:
    """為白名單批次跑 get_insider_modifier。"""
    try:
        out = {}
        for s in symbols or []:
            try:
                out[s] = get_insider_modifier(s)
            except Exception as inner_e:
                logger.warning(f"insider modifier failed for {s} (skip): {inner_e}")
                out[s] = {
                    "tier": "cold_start",
                    "modifiers": {"leaps_entry": 0, "sell_put": 0},
                }
        try:
            write_json("layer_insider_signals_state.json", {
                "dashboard": out,
                "symbols": list(symbols or []),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as we:
            logger.warning(f"insider state write failed (non-fatal): {we}")
        return out
    except Exception as e:
        logger.warning(f"build_insider_dashboard failed (cold-start fallback): {e}")
        return {}
