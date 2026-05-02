"""盤中訊號掃描 (15 分鐘,僅美股交易時段 cron)。

scan_all_signals(mode="intraday") 已注入 priority/push_threshold/tags(Batch 7)。
runner 不過濾 alert_level / priority,Batch 10 router 會做 dedup/quota/cooldown。
"""

from loguru import logger

from src.alerts.alert_formatter import format_signal_alert
from src.alerts.alert_router import route_alert
from src.alerts.tag_attacher import attach_context_tags
from src.signals.final_scorer import scan_all_signals


def main() -> None:
    logger.info("=== run_signal_scan_intraday start ===")
    try:
        alerts = scan_all_signals(mode="intraday") or []
        pushed = 0
        for alert in alerts:
            try:
                alert = attach_context_tags(alert)
                alert["message"] = format_signal_alert(alert)
                if route_alert(alert):
                    pushed += 1
            except Exception as e:
                logger.error(f"intraday per-alert failed (skip): {e}")
        logger.info(
            f"=== run_signal_scan_intraday done "
            f"({len(alerts)} signals, {pushed} pushed) ==="
        )
    except Exception as e:
        logger.error(f"run_signal_scan_intraday crashed: {e}")


if __name__ == "__main__":
    main()
