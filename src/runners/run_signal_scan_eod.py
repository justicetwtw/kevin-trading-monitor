"""盤後訊號掃描 (美股收盤後 cron)。

EOD 跑進場全掃 + 出場規則。intraday 不跑 exit_rules / position_check。
"""

from loguru import logger

from src.alerts.alert_formatter import format_position_alert, format_signal_alert
from src.alerts.alert_router import route_alert
from src.alerts.tag_attacher import attach_context_tags
from src.signals.exit_rules import evaluate_all_exit_rules
from src.signals.final_scorer import scan_all_signals


def main() -> None:
    logger.info("=== run_signal_scan_eod start ===")
    try:
        try:
            alerts = scan_all_signals(mode="eod") or []
        except Exception as e:
            logger.error(f"scan_all_signals(eod) failed: {e}")
            alerts = []
        pushed = 0
        for alert in alerts:
            try:
                alert = attach_context_tags(alert)
                alert["message"] = format_signal_alert(alert)
                if route_alert(alert):
                    pushed += 1
            except Exception as e:
                logger.error(f"eod scan per-alert failed (skip): {e}")

        try:
            exit_alerts = evaluate_all_exit_rules() or []
        except Exception as e:
            logger.error(f"evaluate_all_exit_rules failed: {e}")
            exit_alerts = []
        for ea in exit_alerts:
            try:
                ea.setdefault("kind", "exit_rule")
                ea.setdefault("alert_level", "yellow")
                ea["message"] = format_position_alert(ea)
                if route_alert(ea):
                    pushed += 1
            except Exception as e:
                logger.error(f"exit rule per-alert failed (skip): {e}")

        logger.info(
            f"=== run_signal_scan_eod done "
            f"({len(alerts)} entries + {len(exit_alerts)} exits, {pushed} pushed) ==="
        )
    except Exception as e:
        logger.error(f"run_signal_scan_eod crashed: {e}")


if __name__ == "__main__":
    main()
