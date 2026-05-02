"""Layer 0.6 - VIX 期貨結構(per-signal modifier + leaps_entry_veto)

VIX9D > VIX(短期極恐慌但中期穩):sell_put / leaps_entry +15
VIX > VIX3M(整體恐慌持續):leaps_entry_veto = True
clip 到 LAYER0_SUBMODIFIER_RANGES["vix_structure"]=(-15, 15)。
"""

from datetime import datetime, timezone

from loguru import logger

from src.config.thresholds import LAYER0_SUBMODIFIER_RANGES, VIX_STRUCTURE_RULES
from src.data.vix_structure import fetch_vix_term_structure
from src.storage.state_manager import write_json


_RANGE_KEY = "vix_structure"


def _clip(modifier: int) -> int:
    lo, hi = LAYER0_SUBMODIFIER_RANGES[_RANGE_KEY]
    return int(max(lo, min(hi, modifier)))


def classify_vix_structure() -> dict:
    try:
        data = fetch_vix_term_structure() or {}
        vix = data.get("vix")
        vix9d = data.get("vix9d")

        modifiers = {"sell_put": 0, "leaps_entry": 0, "sell_call": 0}
        leaps_entry_veto = False

        if vix is not None and vix9d is not None:
            if data.get("vix9d_inverted"):
                boost = VIX_STRUCTURE_RULES["vix9d_inversion_modifier"]
                modifiers["sell_put"] = _clip(boost)
                modifiers["leaps_entry"] = _clip(boost)

            if data.get("vix3m_inverted"):
                leaps_entry_veto = True

        result = {
            "snapshot": data,
            "modifiers": modifiers,
            "leaps_entry_veto": bool(leaps_entry_veto),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        if vix is None or vix9d is None:
            result["regime"] = "cold_start"

        try:
            write_json("layer_vix_structure_state.json", result)
        except Exception as we:
            logger.warning(f"vix_structure state write failed (non-fatal): {we}")
        return result
    except Exception as e:
        logger.warning(f"classify_vix_structure failed (cold-start fallback): {e}")
        return {
            "snapshot": {},
            "modifiers": {"sell_put": 0, "leaps_entry": 0, "sell_call": 0},
            "leaps_entry_veto": False,
            "regime": "cold_start",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
        }
