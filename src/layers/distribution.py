"""Layer 0.3 - Distribution Days(per-signal modifier)

SPY + QQQ 各跑一次,取較壞者(count 較高)。
派發級(>=6):leaps -20、sell_put -15、sell_call +5
承壓(4-5):leaps -10、sell_put -5、sell_call 0
健康(0-3):全 0
sell_put / leaps 端 clip 到 LAYER0_SUBMODIFIER_RANGES["distribution_days"]=(-20,0);
sell_call 端 clip 到 (0, 10)(派發日對 sell_call 是正面信號)。
"""

from datetime import datetime, timezone

from loguru import logger

from src.config.thresholds import LAYER0_SUBMODIFIER_RANGES
from src.indicators.distribution_days import detect_distribution_days
from src.storage.state_manager import write_json


_RANGE_KEY = "distribution_days"
_SELL_CALL_RANGE = (0, 10)


def _clip_neg(modifier: int) -> int:
    lo, hi = LAYER0_SUBMODIFIER_RANGES[_RANGE_KEY]
    return int(max(lo, min(hi, modifier)))


def _clip_pos(modifier: int) -> int:
    lo, hi = _SELL_CALL_RANGE
    return int(max(lo, min(hi, modifier)))


def classify_distribution() -> dict:
    """SPY + QQQ 各跑一次,取 count 較壞者。失敗冷啟動全 0。"""
    try:
        spy_dd = detect_distribution_days("SPY") or {}
        qqq_dd = detect_distribution_days("QQQ") or {}
        worst = max(
            (spy_dd, qqq_dd),
            key=lambda x: x.get("count", 0) if isinstance(x, dict) else 0,
        )
        level = worst.get("level", "unknown")

        if level == "distribution":
            mod_leaps, mod_sell_put, mod_sell_call = -20, -15, 5
        elif level == "pressure":
            mod_leaps, mod_sell_put, mod_sell_call = -10, -5, 0
        else:
            mod_leaps, mod_sell_put, mod_sell_call = 0, 0, 0

        result = {
            "spy": spy_dd,
            "qqq": qqq_dd,
            "level": level,
            "modifiers": {
                "leaps_entry": _clip_neg(mod_leaps),
                "sell_put": _clip_neg(mod_sell_put),
                "sell_call": _clip_pos(mod_sell_call),
            },
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            write_json("layer_distribution_state.json", result)
        except Exception as we:
            logger.warning(f"distribution state write failed (non-fatal): {we}")
        return result
    except Exception as e:
        logger.warning(f"classify_distribution failed (cold-start fallback): {e}")
        return {
            "spy": {},
            "qqq": {},
            "level": "cold_start",
            "modifiers": {"leaps_entry": 0, "sell_put": 0, "sell_call": 0},
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
        }
