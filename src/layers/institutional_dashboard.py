"""Layer F.3 - 13F 機構動向(純資料,不在 layer 層做 modifier)

build_institutional_dashboard:純 scan
detect_divergence(symbol, analyst_data, inst_data):分析師上調 vs 機構減倉背離(供 signals 用)
"""

from datetime import datetime, timezone

from loguru import logger

from src.data.institutional_holdings import scan_all_institutions
from src.storage.state_manager import write_json


def build_institutional_dashboard(target_symbols: list) -> dict:
    try:
        out = scan_all_institutions(target_symbols) or {}
        try:
            write_json("layer_institutional_dashboard_state.json", {
                "dashboard": out,
                "target_symbols": list(target_symbols or []),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as we:
            logger.warning(f"institutional dashboard state write failed (non-fatal): {we}")
        return out
    except Exception as e:
        logger.warning(f"build_institutional_dashboard failed (cold-start fallback): {e}")
        return {}


def detect_divergence(symbol: str, analyst_data: dict, inst_data: dict) -> bool:
    """分析師上調 >=2 但 13F 中該股有 >=2 家機構減倉 → True。失敗回 False。"""
    try:
        syms_decreased = (inst_data or {}).get(symbol, {}).get("DECREASED", []) or []
        analyst_upgrades = int((analyst_data or {}).get(symbol, {}).get("upgrades", 0) or 0)
        return bool(analyst_upgrades >= 2 and len(syms_decreased) >= 2)
    except Exception as e:
        logger.warning(f"detect_divergence({symbol}) failed: {e}")
        return False
