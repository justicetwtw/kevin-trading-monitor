"""每日 13F + Form 4 內部人交易掃描 (純 dashboard 更新,不推 alert)。

⚠ Section 12.7 spec 已廢棄(scan_all_insider_signals 不存在)。
偏離決策(B):build_insider_dashboard / build_institutional_dashboard 是 per-symbol modifier dict
而非 alert list,沒有自動推播流。本 runner 只刷新 state,下游由 final_scorer 透過
get_insider_modifier 加分,觸發 sell_put / leaps_entry 訊號時由 route_alert 推。

保留 spec 檔名(GitHub Actions yaml 已寫死)。
"""

from loguru import logger

from src.config.universe import ALL_US_STOCKS
from src.layers.insider_signals import build_insider_dashboard
from src.layers.institutional_dashboard import build_institutional_dashboard


def main() -> None:
    logger.info("=== run_institutional_scan start ===")
    try:
        try:
            inst = build_institutional_dashboard(ALL_US_STOCKS)
            logger.info(f"institutional dashboard updated: {len(inst or {})} symbols")
        except Exception as e:
            logger.error(f"build_institutional_dashboard failed: {e}")

        try:
            insider = build_insider_dashboard(ALL_US_STOCKS)
            logger.info(f"insider dashboard updated: {len(insider or {})} symbols")
        except Exception as e:
            logger.error(f"build_insider_dashboard failed: {e}")

        logger.info("=== run_institutional_scan done ===")
    except Exception as e:
        logger.error(f"run_institutional_scan crashed: {e}")


if __name__ == "__main__":
    main()
