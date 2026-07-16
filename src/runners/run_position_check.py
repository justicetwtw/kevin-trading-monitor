"""Daily private position management and decision-risk check.

Exact positions and account values exist only in memory. Public repository state
contains redacted health metadata, encrypted drawdown values, opaque alert keys,
generic error codes and non-identifying aggregate decision-risk ratios only.
"""

import logging
import sys

from loguru import logger

from src.alerts.alert_formatter import format_position_alert
from src.alerts.alert_router import route_alert
from src.alerts.telegram_bot import send_telegram
from src.config.settings import PRIVATE_POSITION_CONTEXT
from src.management.account_drawdown import update_account_value
from src.management.current_positions import get_account_snapshot
from src.management.hedge_dte_tracker import scan_all_hedges
from src.management.leaps_pnl_tracker import scan_all_leaps
from src.management.portfolio_decision_risk import (
    analyze_portfolio_decision_risk,
    format_private_decision_risk,
    public_decision_risk_state,
)
from src.management.portfolio_risk_summary import (
    analyze_private_portfolio,
    format_private_portfolio_brief,
)
from src.management.private_position_privacy import private_alert_dedup_key
from src.management.short_delta_monitor import scan_all_shorts
from src.storage.state_manager import write_json


def _enable_private_log_guard() -> None:
    """Prevent private tickers/contracts from appearing in public Actions logs."""
    if not PRIVATE_POSITION_CONTEXT:
        return
    logger.disable("src.management")
    logger.disable("src.data")
    for name in ("yfinance", "peewee", "curl_cffi"):
        logging.getLogger(name).setLevel(logging.CRITICAL)


def _position_alert_level(alert: dict, kind: str) -> str:
    """Position exceptions must be routable P1, not silent P2."""
    explicit = alert.get("alert_level")
    if explicit:
        return str(explicit)
    if kind == "leaps_pnl" and alert.get("level") in {"+100", "-40"}:
        return "orange"
    return "green"


def _route_with_kind(alerts, kind: str) -> tuple[int, int]:
    pushed = 0
    failures = 0
    for alert in alerts or []:
        try:
            merged = {
                **alert,
                "kind": kind,
                "alert_level": _position_alert_level(alert, kind),
                "sensitive": True,
            }
            merged["dedup_key"] = private_alert_dedup_key(merged, kind)
            merged["message"] = format_position_alert(merged)
            if route_alert(merged):
                pushed += 1
        except Exception:
            failures += 1
            logger.error(f"{kind} private alert processing failed (details redacted)")
    return pushed, failures


def _public_snapshot(
    snapshot: dict,
    workflow_status: str = "healthy",
    error_codes: list[str] | None = None,
    decision_risk: dict | None = None,
) -> dict:
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
        "valuation_complete": snapshot.get("valuation_complete"),
        "valuation_missing_count": int(
            snapshot.get("valuation_missing_count", 0) or 0
        ),
        "snapshot_at": snapshot.get("snapshot_at"),
        "status": "configured" if configured else "empty",
        "workflow_status": workflow_status,
        "error_codes": sorted(set(error_codes or [])),
        "decision_risk": public_decision_risk_state(decision_risk or {}),
        "privacy": "redacted_public_state",
    }


def _analyze_and_send_private_risk(
    snapshot: dict,
) -> tuple[bool, dict]:
    """Return delivery status plus an in-memory private decision-risk result."""
    if not (snapshot.get("stocks") or snapshot.get("options")):
        return False, {}
    try:
        summary = analyze_private_portfolio(snapshot)
        decision_risk = analyze_portfolio_decision_risk(summary, snapshot)
        message = (
            format_private_portfolio_brief(summary)
            + format_private_decision_risk(decision_risk)
        )
        sent = send_telegram(
            message,
            parse_mode="HTML",
            disable_notification=True,
            sensitive=True,
        )
        return sent, decision_risk
    except Exception:
        logger.error("private portfolio decision-risk brief failed (details redacted)")
        return False, {}


def _scan_safely(scanner, error_code: str, errors: list[str]) -> list:
    try:
        return scanner() or []
    except Exception:
        errors.append(error_code)
        logger.error(f"{error_code} (details redacted)")
        return []


def main() -> int:
    """Run the check and return non-zero when private monitoring is degraded."""
    _enable_private_log_guard()
    logger.info("=== run_position_check start (private details redacted) ===")
    errors: list[str] = []
    pushed = 0

    leaps_alerts = _scan_safely(
        scan_all_leaps, "leaps_scan_failed", errors
    )
    short_alerts = _scan_safely(
        scan_all_shorts, "short_delta_scan_failed", errors
    )
    hedge_alerts = _scan_safely(
        scan_all_hedges, "hedge_scan_failed", errors
    )

    for alerts, kind in (
        (leaps_alerts, "leaps_pnl"),
        (short_alerts, "short_delta"),
        (hedge_alerts, "hedge_dte"),
    ):
        sent, failed = _route_with_kind(alerts, kind)
        pushed += sent
        if failed:
            errors.append(f"{kind}_alert_processing_failed")

    snapshot: dict = {}
    try:
        snapshot = get_account_snapshot() or {}
    except Exception:
        errors.append("snapshot_failed")
        logger.error("snapshot_failed (details redacted)")

    configured = bool(snapshot.get("stocks") or snapshot.get("options"))
    if snapshot.get("mode") == "mode_1" and not configured:
        errors.append("private_positions_missing_or_invalid")

    total = snapshot.get("total_estimated_value")
    if isinstance(total, (int, float)) and total > 0:
        try:
            drawdown = update_account_value(total) or {}
            if (
                drawdown.get("alert_level")
                and drawdown["alert_level"] != "normal"
            ):
                pct = drawdown.get("drawdown_pct")
                pct_str = f"{pct * 100:.1f}%" if pct is not None else "n/a"
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
        except Exception:
            errors.append("drawdown_update_failed")
            logger.error("drawdown_update_failed (details redacted)")
    elif configured:
        # Never update drawdown from a partial portfolio valuation.
        errors.append("account_value_unavailable")

    brief_sent, decision_risk = _analyze_and_send_private_risk(snapshot)
    if configured and not brief_sent:
        errors.append("private_brief_failed")
    if int(decision_risk.get("missing_thesis_id_count", 0) or 0) > 0:
        errors.append("position_thesis_id_missing")
    if int(decision_risk.get("unmapped_symbol_count", 0) or 0) > 0:
        errors.append("position_correlation_basket_unmapped")

    workflow_status = "healthy" if not errors else "degraded"
    public = _public_snapshot(
        snapshot,
        workflow_status,
        errors,
        decision_risk,
    )
    if not write_json("position_snapshot.json", public):
        errors.append("public_snapshot_write_failed")
        workflow_status = "failed"

    logger.info(
        f"=== run_position_check done ({pushed} alerts, "
        f"private_brief_sent={brief_sent}, status={workflow_status}) ==="
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
