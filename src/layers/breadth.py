"""Layer 0.2 - Market Breadth

冷啟動回 modifier=0;輸出 clip 到 LAYER0_SUBMODIFIER_RANGES["breadth"]。
"""

from datetime import datetime, timezone

from loguru import logger

from src.config.thresholds import LAYER0_SUBMODIFIER_RANGES
from src.data.breadth_data import get_breadth_snapshot
from src.storage.state_manager import write_json


_RANGE_KEY = "breadth"


def _clip(modifier: int) -> int:
    lo, hi = LAYER0_SUBMODIFIER_RANGES[_RANGE_KEY]
    return int(max(lo, min(hi, modifier)))


def classify_breadth() -> dict:
    """雙弱→-10、雙強→+10、單弱→-5、其餘 0。失敗冷啟動回 modifier=0。"""
    try:
        snap = get_breadth_snapshot() or {}
        above_50 = snap.get("spx_above_50ma_pct")
        above_200 = snap.get("spx_above_200ma_pct")

        min_mod, max_mod = LAYER0_SUBMODIFIER_RANGES[_RANGE_KEY]

        if above_50 is None or above_200 is None:
            result = {
                "snapshot": snap,
                "modifier": 0,
                "regime": "cold_start",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
        else:
            if above_50 < 40 and above_200 < 50:
                modifier = min_mod
                regime = "weak"
            elif above_50 > 70 and above_200 > 65:
                modifier = max_mod
                regime = "strong"
            elif above_50 < 50 or above_200 < 55:
                modifier = min_mod / 2
                regime = "soft"
            else:
                modifier = 0
                regime = "normal"

            result = {
                "snapshot": snap,
                "modifier": _clip(modifier),
                "regime": regime,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }

        try:
            write_json("layer_breadth_state.json", result)
        except Exception as we:
            logger.warning(f"breadth state write failed (non-fatal): {we}")
        return result
    except Exception as e:
        logger.warning(f"classify_breadth failed (cold-start fallback): {e}")
        return {
            "snapshot": {},
            "modifier": 0,
            "regime": "cold_start",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
        }
