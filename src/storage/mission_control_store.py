"""Trading Monitor v2 Mission Control payload.

This module turns existing state files into a thesis-first, position-aware
summary. It does not call external APIs, publish private holdings or generate
orders.
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
        item for item in items
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


def _local_position_rows(positions: dict[str, Any]) -> list[dict[str, Any]]:
    """Read local-only positions for completeness checks, never for publishing."""
    rows: list[dict[str, Any]] = []
    for stock in _real(positions.get("stocks")):
        rows.append({"kind": "stock", "symbol": stock.get("symbol")})
    for option in _real(positions.get("options")):
        rows.append({"kind": option.get("type", "option"), "symbol": option.get("symbol")})
    return rows


def _build_attention_queue(
    configured: bool,
    snapshot: dict[str, Any],
    theses: list[dict[str, Any]],
    leaps_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []

    if not configured:
        queue.append(_attention(
            "P1",
            "configuration",
            "Cloud position monitoring has no private position input",
            (
                "The public repository intentionally cannot contain real holdings. "
                "Until a secure runtime input is configured, LEAPS, short-delta and "
                "drawdown checks can only see the example file."
            ),
        ))

    if not theses:
        queue.append(_attention(
            "P1",
            "configuration",
            "No symbol-level thesis is tracked",
            (
                "Every real holding and allocation candidate should link to a thesis, "
                "catalyst, invalidation condition and review date."
            ),
        ))

    snapshot_at = snapshot.get("snapshot_at")
    age = _snapshot_age_hours(snapshot_at)
    if not snapshot_at:
        queue.append(_attention(
            "P1",
            "system_health",
            "Position workflow has not published a safe health snapshot",
            (
                "The daily workflow should commit only a redacted health record; exact "
                "symbols, strikes, costs and account value must remain private."
            ),
        ))
    elif age is None:
        queue.append(_attention(
            "P2",
            "system_health",
            "Position snapshot timestamp is invalid",
            f"snapshot_at={snapshot_at!r}",
        ))
    elif age > SNAPSHOT_STALE_HOURS:
        queue.append(_attention(
            "P1",
            "system_health",
            "Position workflow health snapshot is stale",
            f"Last safe snapshot is approximately {age:g} hours old.",
        ))

    # This can surface roll warnings during a local/private build. Public Pages
    # normally has no real positions and therefore publishes no contract detail.
    for row in leaps_payload.get("data", {}).get("positions", []):
        if row.get("roll_warning"):
            queue.append(_attention(
                "P1",
                "position",
                "LEAPS roll-review window reached",
                (
                    f"{row.get('symbol')} {row.get('strike')} {row.get('expiry')} "
                    f"has {row.get('dte')} DTE."
                ),
                row.get("symbol"),
            ))

    today = datetime.now(TIMEZONE_USER).date()
    for thesis in theses:
        symbol = thesis.get("symbol")
        status = str(thesis.get("status", "active"))
        if status in {"broken", "invalidated"}:
            queue.append(_attention(
                "P0",
                "thesis",
                "Thesis marked broken",
                str(thesis.get("summary") or thesis.get("thesis") or "Review required."),
                symbol,
            ))
        elif status in {"watch", "at_risk"}:
            queue.append(_attention(
                "P1",
                "thesis",
                "Thesis needs review",
                str(thesis.get("summary") or thesis.get("thesis") or "Review required."),
                symbol,
            ))

        review_date = _parse_date(thesis.get("next_review"))
        if review_date and review_date <= today:
            queue.append(_attention(
                "P1",
                "review",
                "Scheduled thesis review is due",
                f"Review date: {review_date.isoformat()}",
                symbol,
            ))

    severity_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    return sorted(
        queue,
        key=lambda item: (
            severity_order.get(item["severity"], 9),
            item["category"],
        ),
    )


def build_mission_control_payload() -> dict[str, Any]:
    """Build the dashboard's first-screen decision-support payload."""
    positions_doc = read_json("positions.json", default={})
    snapshot = read_json("position_snapshot.json", default={})
    thesis_doc = read_json("thesis_tracker.json", default={})
    allocation_doc = read_json("capital_allocation.json", default={})

    local_positions = _local_position_rows(
        positions_doc if isinstance(positions_doc, dict) else {}
    )
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
    leaps_payload = dashboard_store.build_leaps_exposure()

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
        allocation_rows.append({
            "manual_rank": candidate.get("manual_rank"),
            "symbol": symbol,
            "theme": candidate.get("theme"),
            "subtheme": candidate.get("subtheme"),
            "status": candidate.get("status", "monitor"),
            "preferred_instrument": candidate.get("preferred_instrument", "wait"),
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
        })

    allocation_rows.sort(key=lambda row: (
        row.get("manual_rank") is None,
        row.get("manual_rank")
        if isinstance(row.get("manual_rank"), int)
        else 9999,
        row.get("symbol") or "",
    ))

    configured = bool(snapshot.get("configured")) or bool(local_positions)
    position_count = snapshot.get("position_count")
    if not isinstance(position_count, int):
        position_count = len(local_positions)

    attention = _build_attention_queue(
        configured, snapshot, theses, leaps_payload
    )
    regime = regime_payload.get("data", {})

    summary = {
        "regime": regime.get("regime"),
        "regime_modifier": regime.get("modifier"),
        "position_configured": configured,
        "position_count": position_count,
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
            "configured": configured,
            "position_count": position_count,
            "total_estimated_value": None,
            "n_long_options": snapshot.get("n_long_options"),
            "n_short_options": snapshot.get("n_short_options"),
            "snapshot_at": snapshot.get("snapshot_at"),
            "privacy": snapshot.get("privacy", "private_detail_not_published"),
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
    return _envelope(data, [
        "positions.json",
        "position_snapshot.json",
        "thesis_tracker.json",
        "capital_allocation.json",
        "layer_macro_regime_state.json",
        "layer_fundamentals_dashboard_state.json",
        "iv_history.json",
    ])
