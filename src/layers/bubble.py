"""Layer 0.4 - Bubble Detector

5 個指標各佔 20 分(buffett / shiller_cape / sp500_top10 / margin_debt / aaii_spread),
合計 0-100。modifier clip 到 LAYER0_SUBMODIFIER_RANGES["bubble"]=(-15, 0)。
"""

from datetime import datetime, timezone

from loguru import logger

from src.config.thresholds import BUBBLE_INDICATORS_THRESHOLDS, LAYER0_SUBMODIFIER_RANGES
from src.data.bubble_indicators import get_bubble_snapshot
from src.storage.state_manager import write_json


_RANGE_KEY = "bubble"


def _clip(modifier: int) -> int:
    lo, hi = LAYER0_SUBMODIFIER_RANGES[_RANGE_KEY]
    return int(max(lo, min(hi, modifier)))


def calc_bubble_score() -> dict:
    """5 個指標各佔 20 分,合 100。失敗冷啟動回 modifier=0。"""
    try:
        snap = get_bubble_snapshot() or {}
        score = 0
        breakdown = {}

        buffett = snap.get("buffett_indicator")
        if buffett:
            thr = BUBBLE_INDICATORS_THRESHOLDS["buffett_indicator"]
            if buffett > thr["bubble"]:
                s = 20
            elif buffett > thr["warning"]:
                s = 12
            elif buffett > thr["normal"]:
                s = 5
            else:
                s = 0
            score += s
            breakdown["buffett"] = {"value": buffett, "score": s}

        cape = snap.get("shiller_cape")
        if cape:
            thr = BUBBLE_INDICATORS_THRESHOLDS["shiller_cape"]
            if cape > thr["bubble"]:
                s = 20
            elif cape > thr["warning"]:
                s = 12
            elif cape > thr["normal"]:
                s = 5
            else:
                s = 0
            score += s
            breakdown["shiller_cape"] = {"value": cape, "score": s}

        conc = snap.get("sp500_top10_concentration")
        if conc:
            thr = BUBBLE_INDICATORS_THRESHOLDS["sp500_top10_concentration"]
            if conc > thr["bubble"]:
                s = 20
            elif conc > thr["warning"]:
                s = 12
            else:
                s = 0
            score += s
            breakdown["concentration"] = {"value": conc, "score": s}

        md = snap.get("margin_debt_yoy")
        if md:
            thr = BUBBLE_INDICATORS_THRESHOLDS["margin_debt_yoy"]
            if md > thr["bubble"]:
                s = 20
            elif md > thr["warning"]:
                s = 12
            else:
                s = 0
            score += s
            breakdown["margin_debt"] = {"value": md, "score": s}

        # AAII bull-bear spread 由 aaii_sentiment 自己處理,這裡跳過

        if score > 80:
            modifier = -15
            stage = "high_alert"
        elif score > 60:
            modifier = -10
            stage = "late"
        elif score > 30:
            modifier = -5
            stage = "mid_late"
        else:
            modifier = 0
            stage = "normal"

        result = {
            "score": int(score),
            "stage": stage,
            "modifier": _clip(modifier),
            "breakdown": breakdown,
            "snapshot": snap,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            write_json("layer_bubble_state.json", result)
        except Exception as we:
            logger.warning(f"bubble state write failed (non-fatal): {we}")
        return result
    except Exception as e:
        logger.warning(f"calc_bubble_score failed (cold-start fallback): {e}")
        return {
            "score": 0,
            "stage": "cold_start",
            "modifier": 0,
            "breakdown": {},
            "snapshot": {},
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
        }
