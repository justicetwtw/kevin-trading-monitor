"""台股訊號掃描 (台股盤後 cron)。

collect_twstock_alerts() 回 [{"signal":..., "message":...}],runner 一行 merge 後 route。
"""

from loguru import logger

from src.alerts.alert_router import route_alert
from src.twstock.twstock_alerts import collect_twstock_alerts


def main() -> None:
    logger.info("=== run_twstock_signal start ===")
    try:
        alerts = collect_twstock_alerts() or []
        pushed = 0
        for a in alerts:
            try:
                merged = {
                    **a["signal"],
                    "message": a["message"],
                    "kind": "twstock",
                    "source": "TW",
                }
                if route_alert(merged):
                    pushed += 1
            except Exception as e:
                logger.error(f"twstock per-alert failed (skip): {e}")
        logger.info(
            f"=== run_twstock_signal done ({len(alerts)} alerts, {pushed} pushed) ==="
        )
    except Exception as e:
        logger.error(f"run_twstock_signal crashed: {e}")


if __name__ == "__main__":
    main()
