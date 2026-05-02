"""部位管理檢查 (每日 EOD cron:LEAPS PnL / Short Delta / Hedge DTE / Drawdown)。

⚠ get_account_snapshot() 會打 yfinance 取股價(N×2 秒),只在 EOD 跑,不在 intraday 跑。
management 模組 alert 缺 kind 欄位,runner 注入後再 route。
"""

from loguru import logger

from src.alerts.alert_formatter import format_position_alert
from src.alerts.alert_router import route_alert
from src.management.account_drawdown import update_account_value
from src.management.current_positions import get_account_snapshot
from src.management.hedge_dte_tracker import scan_all_hedges
from src.management.leaps_pnl_tracker import scan_all_leaps
from src.management.short_delta_monitor import scan_all_shorts


def _route_with_kind(alerts, kind: str) -> int:
    pushed = 0
    for a in alerts or []:
        try:
            merged = {
                **a,
                "kind": kind,
                "alert_level": a.get("alert_level", "yellow"),
            }
            merged["message"] = format_position_alert(merged)
            if route_alert(merged):
                pushed += 1
        except Exception as e:
            logger.error(f"{kind} per-alert failed (skip): {e}")
    return pushed


def main() -> None:
    logger.info("=== run_position_check start ===")
    try:
        try:
            leaps_alerts = scan_all_leaps() or []
        except Exception as e:
            logger.error(f"scan_all_leaps failed: {e}")
            leaps_alerts = []
        try:
            short_alerts = scan_all_shorts() or []
        except Exception as e:
            logger.error(f"scan_all_shorts failed: {e}")
            short_alerts = []
        try:
            hedge_alerts = scan_all_hedges() or []
        except Exception as e:
            logger.error(f"scan_all_hedges failed: {e}")
            hedge_alerts = []

        pushed = 0
        pushed += _route_with_kind(leaps_alerts, "leaps_pnl")
        pushed += _route_with_kind(short_alerts, "short_delta")
        pushed += _route_with_kind(hedge_alerts, "hedge_dte")

        try:
            snapshot = get_account_snapshot() or {}
            total = snapshot.get("total_value")
            if total:
                dd = update_account_value(total) or {}
                if dd.get("alert_level") and dd["alert_level"] != "normal":
                    pct = dd.get("drawdown_pct")
                    pct_str = f"{pct * 100:.1f}%" if pct is not None else "n/a"
                    dd_alert = {
                        "kind": "drawdown",
                        "level": dd.get("alert_level"),
                        "alert_level": "green",
                        "message": f"回撤 {pct_str} — {dd.get('action', '')}",
                    }
                    if route_alert(dd_alert):
                        pushed += 1
            else:
                logger.info("position_check: no total_value (mode_3 / no positions)")
        except Exception as e:
            logger.error(f"drawdown check failed: {e}")

        logger.info(f"=== run_position_check done ({pushed} pushed) ===")
    except Exception as e:
        logger.error(f"run_position_check crashed: {e}")


if __name__ == "__main__":
    main()
