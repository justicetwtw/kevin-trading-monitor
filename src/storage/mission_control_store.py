"""Trading Monitor v2 public Mission Control payload.

This module reads only public-safe state. Exact holdings, contracts, costs and
account values are never loaded into or emitted by the public dashboard.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from src.config.settings import TIMEZONE_USER
from src.storage import dashboard_store
from src.storage.state_manager import read_json

SCHEMA_VERSION = 1
SNAPSHOT_STALE_HOURS = 72


def _envelope(data: dict[str, Any], source_files: list[str]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(TIMEZONE_USER).isoformat(),
        "source_files": source_files,
        "data": data,
    }


def _real(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    return [
        item
        for item in items
        if isinstance(item, dict) and not item.get("_example")
    ]


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _snapshot_age_hours(snapshot_at: Any) -> float | None:
    if not isinstance(snapshot_at, str) or not snapshot_at:
        return None
    try:
        value = datetime.fromisoformat(snapshot_at.replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=TIMEZONE_USER)
        now = datetime.now(value.tzinfo)
        return round((now - value).total_seconds() / 3600, 1)
    except (TypeError, ValueError):
        return None


def _attention(
    severity: str,
    category: str,
    title: str,
    detail: str,
    symbol: str | None = None,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "category": category,
        "symbol": symbol,
        "title": title,
        "detail": detail,
    }


def _build_attention_queue(
    snapshot: dict[str, Any],
    drawdown_state: dict[str, Any],
    theses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    configured = bool(snapshot.get("configured"))
    source = snapshot.get("position_source")
    workflow_status = str(snapshot.get("workflow_status") or "unknown")
    error_codes = [
        str(value)
        for value in (snapshot.get("error_codes") or [])
        if value
    ]

    if not configured:
        queue.append(
            _attention(
                "P1",
                "configuration",
                "Cloud position monitoring has no valid private position input",
                (
                    "Create POSITIONS_JSON and POSITION_STATE_KEY in GitHub "
                    "Actions secrets, then manually run Position Management Check."
                ),
            )
        )
    elif source != "actions_secret":
        queue.append(
            _attention(
                "P1",
                "configuration",
                "Position workflow is not using the encrypted Actions input",
                f"Public health snapshot reports position_source={source!r}.",
            )
        )

    if workflow_status in {"degraded", "failed"} or error_codes:
        severity = "P0" if workflow_status == "failed" else "P1"
        queue.append(
            _attention(
                severity,
                "system_health",
                "Private position workflow is degraded",
                (
                    "Safe error codes: " + ", ".join(error_codes)
                    if error_codes
                    else f"workflow_status={workflow_status}"
                ),
            )
        )

    snapshot_at = snapshot.get("snapshot_at")
    age = _snapshot_age_hours(snapshot_at)
    if not snapshot_at:
        queue.append(
            _attention(
                "P1",
                "system_health",
                "Position workflow has not published a safe health snapshot",
                (
                    "The daily workflow should commit only aggregate counts, "
                    "generic error codes and timestamps."
                ),
            )
        )
    elif age is None:
        queue.append(
            _attention(
                "P2",
                "system_health",
                "Position snapshot timestamp is invalid",
                f"snapshot_at={snapshot_at!r}",
            )
        )
    elif age > SNAPSHOT_STALE_HOURS:
        queue.append(
            _attention(
                "P1",
                "system_health",
                "Position workflow health snapshot is stale",
                f"Last safe snapshot is approximately {age:g} hours old.",
            )
        )

    if drawdown_state:
        key_source = drawdown_state.get("key_source")
        if key_source and key_source != "actions_secret":
            queue.append(
                _attention(
                    "P1",
                    "configuration",
                    "Drawdown high-water state is not using the stable secret key",
                    (
                        "POSITION_STATE_KEY is missing or invalid; cross-run "
                        "drawdown peak will reset safely instead of persisting."
                    ),
                )
            )
        if "peak" in drawdown_state or "current" in drawdown_state:
            queue.append(
                _attention(
                    "P0",
                    "privacy",
                    "Public drawdown state contains plaintext account values",
                    "Remove peak/current and rotate POSITION_STATE_KEY if exposed.",
                )
            )

    today = datetime.now(TIMEZONE_USER).date()
    for thesis in theses:
        symbol = thesis.get("symbol")
        status = str(thesis.get("status", "active"))
        if status in {"broken", "invalidated"}:
            queue.append(
                _attention(
                    "P0",
                    "thesis",
                    "Thesis marked broken",
                    str(
                        thesis.get("summary")
                        or thesis.get("thesis")
                        or "Review required."
                    ),
                    symbol,
                )
            )
        elif status in {"watch", "at_risk"}:
            queue.append(
                _attention(
                    "P1",
                    "thesis",
                    "Thesis needs review",
                    str(
                        thesis.get("summary")
                        or thesis.get("thesis")
                        or "Review required."
                    ),
                    symbol,
                )
            )

        review_date = _parse_date(thesis.get("next_review"))
        if review_date and review_date <= today:
            queue.append(
                _attention(
                    "P1",
                    "review",
                    "Scheduled thesis review is due",
                    f"Review date: {review_date.isoformat()}",
                    symbol,
                )
            )

    severity_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    return sorted(
        queue,
        key=lambda item: (
            severity_order.get(item["severity"], 9),
            item["category"],
            item.get("symbol") or "",
        ),
    )


def build_mission_control_payload() -> dict[str, Any]:
    """Build the dashboard first-screen decision-support payload."""
    snapshot = read_json("position_snapshot.json", default={})
    drawdown_state = read_json("drawdown_history.json", default={})
    thesis_doc = read_json("thesis_tracker.json", default={})
    allocation_doc = read_json("capital_allocation.json", default={})

    if not isinstance(snapshot, dict):
        snapshot = {}
    if not isinstance(drawdown_state, dict):
        drawdown_state = {}

    themes = thesis_doc.get("themes", []) if isinstance(thesis_doc, dict) else []
    theses = thesis_doc.get("symbols", []) if isinstance(thesis_doc, dict) else []
    candidates = (
        allocation_doc.get("candidates", [])
        if isinstance(allocation_doc, dict)
        else []
    )
    themes = _real(themes)
    theses = _real(theses)
    candidates = _real(candidates)

    regime_payload = dashboard_store.build_regime_payload()
    watchlist_payload = dashboard_store.build_watchlist_scores()
    options_payload = dashboard_store.build_options_flow()

    watchlist_by_symbol = {
        row.get("symbol"): row
        for row in watchlist_payload.get("data", {}).get("rows", [])
        if isinstance(row, dict)
    }
    options_by_symbol = {
        row.get("symbol"): row
        for row in options_payload.get("data", {}).get("rows", [])
        if isinstance(row, dict)
    }

    allocation_rows: list[dict[str, Any]] = []
    for candidate in candidates:
        symbol = candidate.get("symbol")
        score = watchlist_by_symbol.get(symbol, {})
        option_state = options_by_symbol.get(symbol, {})
        allocation_rows.append(
            {
                "manual_rank": candidate.get("manual_rank"),
                "symbol": symbol,
                "theme": candidate.get("theme"),
                "subtheme": candidate.get("subtheme"),
                "status": candidate.get("status", "monitor"),
                "preferred_instrument": candidate.get(
                    "preferred_instrument", "wait"
                ),
                "reason": candidate.get("reason"),
                "trigger": candidate.get("trigger"),
                "invalidation": candidate.get("invalidation"),
                "total_score": score.get("total_score"),
                "coverage": score.get("coverage"),
                "action_band": score.get("action_band"),
                "ivr": option_state.get("ivr"),
                "ivp": option_state.get("ivp"),
                "options_status": option_state.get(
                    "status", "not_in_dashboard_universe"
                ),
                "not_a_trade_signal": True,
            }
        )

    allocation_rows.sort(
        key=lambda row: (
            row.get("manual_rank") is None,
            row.get("manual_rank")
            if isinstance(row.get("manual_rank"), int)
            else 9999,
            row.get("symbol") or "",
        )
    )

    configured = bool(snapshot.get("configured"))
    position_count = snapshot.get("position_count")
    if not isinstance(position_count, int):
        position_count = 0

    attention = _build_attention_queue(snapshot, drawdown_state, theses)
    regime = regime_payload.get("data", {})

    summary = {
        "regime": regime.get("regime"),
        "regime_modifier": regime.get("modifier"),
        "position_configured": configured,
        "position_count": position_count,
        "position_source": snapshot.get("position_source"),
        "position_workflow_status": snapshot.get("workflow_status"),
        "estimated_account_value": None,
        "snapshot_at": snapshot.get("snapshot_at"),
        "snapshot_age_hours": _snapshot_age_hours(snapshot.get("snapshot_at")),
        "tracked_theme_count": len(themes),
        "tracked_thesis_count": len(theses),
        "allocation_candidate_count": len(allocation_rows),
        "needs_attention_count": len(attention),
    }

    data = {
        "summary": summary,
        "attention": attention,
        "account": {
            "mode": snapshot.get("mode"),
            "position_source": snapshot.get("position_source"),
            "workflow_status": snapshot.get("workflow_status"),
            "error_codes": list(snapshot.get("error_codes") or []),
            "configured": configured,
            "position_count": position_count,
            "total_estimated_value": None,
            "n_long_options": snapshot.get("n_long_options"),
            "n_short_options": snapshot.get("n_short_options"),
            "snapshot_at": snapshot.get("snapshot_at"),
            "drawdown_pct": drawdown_state.get("drawdown_pct"),
            "drawdown_alert_level": drawdown_state.get("alert_level"),
            "drawdown_key_source": drawdown_state.get("key_source"),
            "privacy": snapshot.get(
                "privacy", "private_detail_not_published"
            ),
            "positions": [],
        },
        "themes": themes,
        "theses": theses,
        "allocation_queue": allocation_rows,
        "disclaimer": (
            "Decision support only. Public dashboard state intentionally excludes "
            "exact holdings, strikes, costs and account value. It never creates an "
            "order or substitutes for Kevin's judgment."
        ),
    }
    return _envelope(
        data,
        [
            "position_snapshot.json",
            "drawdown_history.json",
            "thesis_tracker.json",
            "capital_allocation.json",
            "layer_macro_regime_state.json",
            "layer_fundamentals_dashboard_state.json",
            "iv_history.json",
        ],
    )
