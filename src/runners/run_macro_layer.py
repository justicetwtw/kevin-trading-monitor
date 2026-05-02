"""每日宏觀層更新 (Layer 0 / 0+ / F)。

⚠ Section 12.6 spec 已廢棄(全 update_* 函式不存在)。
真實實作:layers 全部叫 classify_* / calc_* / build_*_dashboard / aggregate_layer0。
fundamentals_dashboard 需傳 symbols(spec 寫 refresh_universe_fundamentals 無參數)。

純呼叫,失敗單點 log 不拖垮整支。最後 aggregate_layer0 寫 layer0_state.json 給 final_scorer 讀。
"""

from loguru import logger

from src.config.universe import ALL_US_STOCKS
from src.layers.breadth import classify_breadth
from src.layers.bubble import calc_bubble_score
from src.layers.distribution import classify_distribution
from src.layers.fundamentals_dashboard import build_fundamentals_dashboard
from src.layers.macro_regime import classify_macro_regime
from src.layers.modifier_aggregator import aggregate_layer0
from src.layers.put_call import classify_put_call
from src.layers.vix_structure_layer import classify_vix_structure


def _safe(name: str, fn, *args, **kwargs):
    try:
        result = fn(*args, **kwargs)
        logger.info(f"{name} ok")
        return result
    except Exception as e:
        logger.error(f"{name} failed: {e}")
        return None


def main() -> None:
    logger.info("=== run_macro_layer start ===")
    try:
        _safe("classify_macro_regime", classify_macro_regime)
        _safe("classify_breadth", classify_breadth)
        _safe("classify_distribution", classify_distribution)
        _safe("calc_bubble_score", calc_bubble_score)
        _safe("classify_put_call", classify_put_call)
        _safe("classify_vix_structure", classify_vix_structure)
        _safe(
            "build_fundamentals_dashboard",
            build_fundamentals_dashboard,
            ALL_US_STOCKS,
        )
        dashboard = _safe("aggregate_layer0", aggregate_layer0)
        if dashboard:
            summary = dashboard.get("summary", {}) if isinstance(dashboard, dict) else {}
            logger.info(f"Macro dashboard summary: {summary}")
        logger.info("=== run_macro_layer done ===")
    except Exception as e:
        logger.error(f"run_macro_layer crashed: {e}")


if __name__ == "__main__":
    main()
