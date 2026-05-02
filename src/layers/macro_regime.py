"""Layer 0.1 - Macro Regime Score

五子指標各佔 20%:10Y-2Y / HY OAS / DXY / VIX / Copper-Gold ratio
冷啟動回 modifier=0(子層中性,非 None);輸出 clip 到 LAYER0_SUBMODIFIER_RANGES["macro_regime"]。
"""

from datetime import datetime, timezone

import yfinance as yf
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_not_exception_type

from src.config.thresholds import LAYER0_SUBMODIFIER_RANGES
from src.data.fred_api import get_yield_curve_spread, get_hy_credit_spread, get_dxy
from src.data.vix_structure import fetch_vix_term_structure
from src.storage.state_manager import write_json


_RANGE_KEY = "macro_regime"


def _clip(modifier: int) -> int:
    lo, hi = LAYER0_SUBMODIFIER_RANGES[_RANGE_KEY]
    return int(max(lo, min(hi, modifier)))


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_not_exception_type((ValueError, RuntimeError)),
    reraise=True,
)
def get_copper_gold_ratio() -> float | None:
    """Copper / Gold 比率(用 ETF 替代:CPER / GLD)。失敗回 None。"""
    try:
        copper_hist = yf.Ticker("CPER").history(period="5d")
        gold_hist = yf.Ticker("GLD").history(period="5d")
        if copper_hist.empty or gold_hist.empty:
            return None
        copper = copper_hist["Close"].iloc[-1]
        gold = gold_hist["Close"].iloc[-1]
        if not gold:
            return None
        return float(copper / gold)
    except Exception as e:
        logger.warning(f"copper_gold_ratio fetch failed: {e}")
        return None


def classify_macro_regime() -> dict:
    """五子指標分類 + 整體評分。失敗或全 None 冷啟動回 modifier=0。"""
    try:
        indicators = {}

        spread = get_yield_curve_spread()
        indicators["yield_curve"] = {
            "value": spread,
            "regime": (
                "risk_on" if spread is not None and spread > 0 else
                "risk_off" if spread is not None and spread < -50 else
                "neutral"
            ),
        }

        hy = get_hy_credit_spread()
        indicators["hy_oas"] = {
            "value": hy,
            "regime": (
                "risk_on" if hy is not None and hy < 300 else
                "risk_off" if hy is not None and hy > 500 else
                "neutral"
            ),
        }

        dxy = get_dxy()
        indicators["dxy"] = {
            "value": dxy,
            "regime": (
                "risk_on" if dxy is not None and dxy < 100 else
                "risk_off" if dxy is not None and dxy > 105 else
                "neutral"
            ),
        }

        vix_data = fetch_vix_term_structure() or {}
        vix = vix_data.get("vix")
        indicators["vix"] = {
            "value": vix,
            "regime": (
                "risk_on" if vix is not None and vix < 18 else
                "risk_off" if vix is not None and vix > 25 else
                "neutral"
            ),
        }

        try:
            cg = get_copper_gold_ratio()
        except Exception as e:
            logger.warning(f"copper_gold_ratio retry exhausted: {e}")
            cg = None
        indicators["copper_gold"] = {"value": cg, "regime": "neutral"}

        risk_on_count = sum(1 for v in indicators.values() if v["regime"] == "risk_on")
        risk_off_count = sum(1 for v in indicators.values() if v["regime"] == "risk_off")

        min_mod, max_mod = LAYER0_SUBMODIFIER_RANGES[_RANGE_KEY]
        if risk_off_count >= 3:
            modifier = min_mod
        elif risk_off_count == 2:
            modifier = min_mod / 2
        elif risk_on_count >= 3:
            modifier = max_mod
        elif risk_on_count == 2:
            modifier = max_mod / 2
        else:
            modifier = 0

        result = {
            "indicators": indicators,
            "risk_on_count": int(risk_on_count),
            "risk_off_count": int(risk_off_count),
            "modifier": _clip(modifier),
            "regime": (
                "risk_off" if risk_off_count >= 3 else
                "risk_on" if risk_on_count >= 3 else
                "neutral"
            ),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            write_json("layer_macro_regime_state.json", result)
        except Exception as we:
            logger.warning(f"macro_regime state write failed (non-fatal): {we}")
        return result
    except Exception as e:
        logger.warning(f"classify_macro_regime failed (cold-start fallback): {e}")
        return {
            "indicators": {},
            "risk_on_count": 0,
            "risk_off_count": 0,
            "modifier": 0,
            "regime": "cold_start",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
        }
