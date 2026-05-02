"""Layer 0.5 - Put/Call Ratio(per-signal modifier)

extreme_fear(>1.20):sell_put +10、leaps_entry +10、sell_call 0
extreme_greed(<0.70):sell_put 0、leaps_entry 0、sell_call +10
neutral / 冷啟動:全 0
clip 到 LAYER0_SUBMODIFIER_RANGES["put_call_ratio"]=(-10, 10)。
"""

from datetime import datetime, timezone

from loguru import logger

from src.config.thresholds import LAYER0_SUBMODIFIER_RANGES, PUT_CALL_RATIO_THRESHOLDS
from src.data.put_call_ratio import get_put_call_ratio
from src.storage.state_manager import write_json


_RANGE_KEY = "put_call_ratio"


def _clip(modifier: int) -> int:
    lo, hi = LAYER0_SUBMODIFIER_RANGES[_RANGE_KEY]
    return int(max(lo, min(hi, modifier)))


def classify_put_call() -> dict:
    try:
        pcr_data = get_put_call_ratio() or {}
        pcr = pcr_data.get("pcr")

        if pcr is None:
            result = {
                "pcr": None,
                "regime": "cold_start",
                "modifiers": {"sell_put": 0, "sell_call": 0, "leaps_entry": 0},
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
        else:
            thr = PUT_CALL_RATIO_THRESHOLDS
            if pcr > thr["extreme_fear"]:
                regime = "extreme_fear"
                mods = {"sell_put": 10, "leaps_entry": 10, "sell_call": 0}
            elif pcr < thr["extreme_greed"]:
                regime = "extreme_greed"
                mods = {"sell_put": 0, "leaps_entry": 0, "sell_call": 10}
            else:
                regime = "neutral"
                mods = {"sell_put": 0, "leaps_entry": 0, "sell_call": 0}
            result = {
                "pcr": float(pcr),
                "source": pcr_data.get("source"),
                "regime": regime,
                "modifiers": {k: _clip(v) for k, v in mods.items()},
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }

        try:
            write_json("layer_put_call_state.json", result)
        except Exception as we:
            logger.warning(f"put_call state write failed (non-fatal): {we}")
        return result
    except Exception as e:
        logger.warning(f"classify_put_call failed (cold-start fallback): {e}")
        return {
            "pcr": None,
            "regime": "cold_start",
            "modifiers": {"sell_put": 0, "sell_call": 0, "leaps_entry": 0},
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
        }
