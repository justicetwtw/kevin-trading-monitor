"""Layer F.2 - 分析師動向(per-symbol modifier)

build_analyst_dashboard(symbols, lookback_days):純 fetch
get_analyst_modifier(symbol):upgrades>=2 → +5, downgrades>=2 → -5, sell_call_veto = upgrades>=2
clip 到 (-10, +10)(LEAPS modifier 容許範圍)。
"""

from datetime import datetime, timezone

from loguru import logger

from src.data.analyst_actions import fetch_analyst_actions
from src.storage.state_manager import write_json


_LEAPS_RANGE = (-10, 10)


def _clip(modifier: int) -> int:
    lo, hi = _LEAPS_RANGE
    return int(max(lo, min(hi, modifier)))


def build_analyst_dashboard(symbols: list, lookback_days: int = 7) -> dict:
    try:
        out = {}
        for s in symbols or []:
            try:
                out[s] = fetch_analyst_actions(s, lookback_days)
            except Exception as inner_e:
                logger.warning(f"analyst fetch failed for {s} (skip): {inner_e}")
                out[s] = {"upgrades": 0, "downgrades": 0, "actions": []}

        try:
            write_json("layer_analyst_dashboard_state.json", {
                "dashboard": out,
                "symbols": list(symbols or []),
                "lookback_days": lookback_days,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as we:
            logger.warning(f"analyst dashboard state write failed (non-fatal): {we}")
        return out
    except Exception as e:
        logger.warning(f"build_analyst_dashboard failed (cold-start fallback): {e}")
        return {}


def get_analyst_modifier(symbol: str) -> dict:
    """LEAPS 訊號加成 / 賣 CALL 否決參考。失敗冷啟動回 modifier=0。"""
    try:
        data = fetch_analyst_actions(symbol, 7) or {}
        upgrades = int(data.get("upgrades", 0) or 0)
        downgrades = int(data.get("downgrades", 0) or 0)

        modifier = 0
        if upgrades >= 2:
            modifier += 5
        if downgrades >= 2:
            modifier -= 5

        return {
            "data": data,
            "leaps_modifier": _clip(modifier),
            "sell_call_veto": bool(upgrades >= 2),
        }
    except Exception as e:
        logger.warning(f"get_analyst_modifier({symbol}) failed (cold-start fallback): {e}")
        return {
            "data": {},
            "leaps_modifier": 0,
            "sell_call_veto": False,
            "error": str(e),
        }
