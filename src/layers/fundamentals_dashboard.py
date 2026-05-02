"""Layer F.1 - 基本面儀表板(純資料,不在 layer 層做 modifier)

只 build dashboard;modifier 規則由 Batch 7 signals 層在讀 dashboard 時自己算。
"""

from datetime import datetime, timezone

from loguru import logger

from src.data.fundamentals import fetch_fundamentals
from src.storage.state_manager import write_json


def build_fundamentals_dashboard(symbols: list) -> dict:
    """為白名單建立基本面快照。失敗回 {}。"""
    try:
        out = {}
        for s in symbols or []:
            try:
                out[s] = fetch_fundamentals(s)
            except Exception as inner_e:
                logger.warning(f"fundamentals fetch failed for {s} (skip): {inner_e}")
                out[s] = {}

        try:
            write_json("layer_fundamentals_dashboard_state.json", {
                "dashboard": out,
                "symbols": list(symbols or []),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as we:
            logger.warning(f"fundamentals dashboard state write failed (non-fatal): {we}")
        return out
    except Exception as e:
        logger.warning(f"build_fundamentals_dashboard failed (cold-start fallback): {e}")
        return {}
