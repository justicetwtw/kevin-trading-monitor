"""統一彙整所有 Layer 0 → 給 signals/ 使用(per-signal 三維)

aggregate_layer0() 回傳:
  {
    "scan_time": ISO with tz,
    "submodules": {macro_regime, breadth, distribution, bubble, put_call, vix_structure, aaii},
    "aggregate_modifiers": {
        "sell_call": int (clip -30..+20),
        "sell_put":  int (clip -30..+20),
        "leaps_entry": int (clip -30..+20),
        "leaps_entry_veto": bool,
    },
  }

Layer F (per-symbol) 不在這裡彙整,signals 層自己讀 dashboard。
冷啟動:任一 sub-layer 失敗 → 該層 modifier=0,aggregate 仍正確 clip。
"""

from datetime import datetime, timezone

from loguru import logger

from src.config.thresholds import LAYER0_MODIFIER_MIN, LAYER0_MODIFIER_MAX
from src.layers.macro_regime import classify_macro_regime
from src.layers.breadth import classify_breadth
from src.layers.distribution import classify_distribution
from src.layers.bubble import calc_bubble_score
from src.layers.put_call import classify_put_call
from src.layers.vix_structure_layer import classify_vix_structure
from src.layers.aaii_sentiment import classify_aaii
from src.storage.state_manager import write_json


def _clip_total(value: float) -> int:
    return int(max(LAYER0_MODIFIER_MIN, min(LAYER0_MODIFIER_MAX, value)))


def _safe_call(name: str, fn, fallback: dict) -> dict:
    try:
        result = fn()
        return result if isinstance(result, dict) else fallback
    except Exception as e:
        logger.error(f"aggregate_layer0: {name} failed → cold_start: {e}")
        return fallback


def _aggregate_per_signal_type(submodules: dict) -> dict:
    """根據三大訊號類型,加總對應的 modifiers 並 clip 到 LAYER0_MODIFIER_MIN/MAX。"""
    macro_mod = submodules.get("macro_regime", {}).get("modifier", 0) or 0
    breadth_mod = submodules.get("breadth", {}).get("modifier", 0) or 0
    bubble_mod = submodules.get("bubble", {}).get("modifier", 0) or 0
    aaii_mod = submodules.get("aaii", {}).get("modifier", 0) or 0

    sell_put_mod = macro_mod + breadth_mod + bubble_mod + aaii_mod
    leaps_entry_mod = macro_mod + breadth_mod + bubble_mod + aaii_mod
    sell_call_mod = -macro_mod * 0.3  # 對賣 CALL 反向、且權重較弱

    dist = submodules.get("distribution", {}).get("modifiers", {}) or {}
    sell_call_mod += dist.get("sell_call", 0) or 0
    sell_put_mod += dist.get("sell_put", 0) or 0
    leaps_entry_mod += dist.get("leaps_entry", 0) or 0

    pcr = submodules.get("put_call", {}).get("modifiers", {}) or {}
    sell_call_mod += pcr.get("sell_call", 0) or 0
    sell_put_mod += pcr.get("sell_put", 0) or 0
    leaps_entry_mod += pcr.get("leaps_entry", 0) or 0

    vix = submodules.get("vix_structure", {}).get("modifiers", {}) or {}
    sell_call_mod += vix.get("sell_call", 0) or 0
    sell_put_mod += vix.get("sell_put", 0) or 0
    leaps_entry_mod += vix.get("leaps_entry", 0) or 0
    leaps_entry_veto = bool(submodules.get("vix_structure", {}).get("leaps_entry_veto", False))

    return {
        "sell_call": _clip_total(sell_call_mod),
        "sell_put": _clip_total(sell_put_mod),
        "leaps_entry": _clip_total(leaps_entry_mod),
        "leaps_entry_veto": leaps_entry_veto,
    }


def aggregate_layer0() -> dict:
    """跑全部 7 個 Layer 0 子模組,回傳彙整 dict。永遠回 dict,不拋例外。"""
    out = {
        "scan_time": datetime.now(timezone.utc).isoformat(),
        "submodules": {},
    }

    cold_dict_modifier = {"modifier": 0, "regime": "cold_start"}
    cold_dict_per_signal = {
        "modifiers": {"sell_put": 0, "sell_call": 0, "leaps_entry": 0},
        "leaps_entry_veto": False,
        "regime": "cold_start",
    }

    out["submodules"]["macro_regime"] = _safe_call(
        "macro_regime", classify_macro_regime, cold_dict_modifier
    )
    out["submodules"]["breadth"] = _safe_call(
        "breadth", classify_breadth, cold_dict_modifier
    )
    out["submodules"]["distribution"] = _safe_call(
        "distribution", classify_distribution, cold_dict_per_signal
    )
    out["submodules"]["bubble"] = _safe_call(
        "bubble", calc_bubble_score, cold_dict_modifier
    )
    out["submodules"]["put_call"] = _safe_call(
        "put_call", classify_put_call, cold_dict_per_signal
    )
    out["submodules"]["vix_structure"] = _safe_call(
        "vix_structure", classify_vix_structure, cold_dict_per_signal
    )
    out["submodules"]["aaii"] = _safe_call(
        "aaii", classify_aaii, cold_dict_modifier
    )

    out["aggregate_modifiers"] = _aggregate_per_signal_type(out["submodules"])

    try:
        write_json("layer0_history.json", out)
    except Exception as we:
        logger.warning(f"layer0_history write failed (non-fatal): {we}")

    return out
