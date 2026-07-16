"""Daily private position management check.

Exact positions and account values exist only in memory. Public repository state
contains redacted health metadata, encrypted drawdown values and opaque alert
keys only.
"""

from loguru import logger

from src.alerts.alert_formatter import format_position_alert
from src.alerts.alert_router import route_alert
from src.management.account_drawdown import update_account_value
from src.management.current_positions import get_account_snapshot
from src.management.hedge_dte_tracker import scan_all_hedges
from src.management.leaps_pnl_tracker import scan_all_leaps
from src.management.private_position_privacy import private_alert_dedup_key
from src.management.short_delta_monitor import scan_all_shorts
from src.storage.state_manager import write_json


def _route_with_kind(alerts, kind: str) -> int:
    pushed = 0
    for alert in alerts or []:
        try:
            merged = {
                **alert,
                "kind": kind,
                "alert_level": alert.get("alert_level", "yellow"),
                "sensitive": True,
            }
            merged["dedup_key"] = private_alert_dedup_key(merged, kind)
            merged["message"] = format_position_alert(merged)
            if route_alert(merged):
                pushed += 1
        except Exception as exc:
            logger.error(f"{kind} per-alert failed (skip): {exc}")
    return pushed


def _public_snapshot(snapshot: dict) -> dict:
    """Return aggregate state safe to commit in a public repository."""
    stocks = snapshot.get("stocks") or []
    options = snapshot.get("options") or []
    configured = bool(stocks or options)
    return {
        "mode": snapshot.get("mode"),
        "position_source": snapshot.get("position_source"),
        "configured": configured,
        "position_count": len(stocks) + len(options),
        "n_long_options": int(snapshot.get("n_long_options", 0) or 0),
        "n_short_options": int(snapshot.get("n_short_options", 0) or 0),
        "snapshot_at": snapshot.get("snapshot_at"),
        "status": "configured" if configured else "empty",
        "privacy": "redacted_public_state",
    }


def main() -> None:
    logger.info("=== run_position_check start ===")
    try:
        try:
            leaps_alerts = scan_all_leaps() or []
        except Exception as exc:
            logger.error(f"scan_all_leaps failed: {exc}")
            leaps_alerts = []
        try:
            short_alerts = scan_all_shorts() or []
        except Exception as exc:
            logger.error(f"scan_all_shorts failed: {exc}")
            short_alerts = []
        try:
            hedge_alerts = scan_all_hedges() or []
        except Exception as exc:
            logger.error(f"scan_all_hedges failed: {exc}")
            hedge_alerts = []

        pushed = 0
        pushed += _route_with_kind(leaps_alerts, "leaps_pnl")
        pushed += _route_with_kind(short_alerts, "short_delta")
        pushed += _route_with_kind(hedge_alerts, "hedge_dte")

        try:
            snapshot = get_account_snapshot() or {}
            if not write_json(
                "position_snapshot.json", _public_snapshot(snapshot)
            ):
                logger.error(
                    "position_check: failed to persist redacted position snapshot"
                )

            # `get_account_snapshot` returns `total_estimated_value`. The old
            # runner used `total_value`, so drawdown tracking never ran.
            total = snapshot.get("total_estimated_value")
            if isinstance(total, (int, float)) and total > 0:
                drawdown = update_account_value(total) or {}
                if (
                    drawdown.get("alert_level")
                    and drawdown["alert_level"] != "normal"
                ):
                    pct = drawdown.get("drawdown_pct")
                    pct_str = (
                        f"{pct * 100:.1f}%" if pct is not None else "n/a"
                    )
                    drawdown_alert = {
                        "kind": "drawdown",
                        "level": drawdown.get("alert_level"),
                        "alert_level": "green",
                        "sensitive": True,
                        "dedup_key": "private-position::account-drawdown",
                        "message": (
                            f"回撤 {pct_str} — {drawdown.get('action', '')}"
                        ),
                    }
                    if route_alert(drawdown_alert):
                        pushed += 1
            else:
                logger.info(
                    "position_check: no positive total_estimated_value "
                    "(mode_3 / no positions)"
                )
        except Exception as exc:
            logger.error(f"drawdown/snapshot check failed: {exc}")

        logger.info(f"=== run_position_check done ({pushed} pushed) ===")
    except Exception as exc:
        logger.error(f"run_position_check crashed: {exc}")


if __name__ == "__main__":
    main()
