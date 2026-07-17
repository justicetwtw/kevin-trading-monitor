"""Build and inject the public-safe decision layer into Mission Control."""

from __future__ import annotations

import html
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from src.decision.decision_grade import MAX_MARKET_CONTEXT_AGE_DAYS
from src.decision.opportunity_ranker import build_decision_payload
from src.storage import dashboard_store
from src.storage.state_manager import read_json

START = "<!-- decision-layer:start -->"
END = "<!-- decision-layer:end -->"


def _market_context_is_stale(
    generated_at: Any, *, today: date | None = None
) -> bool:
    """A frozen snapshot must degrade the health strip, not stay green."""
    if not isinstance(generated_at, str) or not generated_at:
        return True
    try:
        generated = datetime.fromisoformat(
            generated_at.replace("Z", "+00:00")
        ).date()
    except ValueError:
        return True
    reference = today or datetime.now(timezone.utc).date()
    return (reference - generated).days > MAX_MARKET_CONTEXT_AGE_DAYS


def build_from_store() -> dict[str, Any]:
    allocation = read_json("capital_allocation.json", default={})
    thesis = read_json("thesis_tracker.json", default={})
    market = read_json("decision_market_context.json", default={})
    decision_log = read_json("decision_log.json", default=[])
    position_snapshot = read_json("position_snapshot.json", default={})
    if not isinstance(allocation, dict):
        allocation = {}
    if not isinstance(thesis, dict):
        thesis = {}
    if not isinstance(market, dict):
        market = {}
    if not isinstance(position_snapshot, dict):
        position_snapshot = {}
    payload = build_decision_payload(
        allocation_doc=allocation,
        thesis_doc=thesis,
        watchlist_payload=dashboard_store.build_watchlist_scores(),
        options_payload=dashboard_store.build_options_flow(),
        market_context_doc=market,
        decision_log=decision_log,
    )
    public_risk = position_snapshot.get("decision_risk")
    payload["portfolio_decision_risk"] = (
        public_risk if isinstance(public_risk, dict) else {}
    )
    stale = _market_context_is_stale(market.get("generated_at"))
    payload["market_context_health"] = {
        "status": market.get("status"),
        "stale": stale,
        "generated_at": market.get("generated_at"),
        "unavailable_count": market.get("unavailable_count"),
        "partial_count": market.get("partial_count"),
        "contract": market.get("contract"),
    }
    return payload


def _e(value: Any) -> str:
    """Escape and plainly format a value; never guess percent from range."""
    if value is None or value == "":
        return "—"
    if isinstance(value, float):
        text = f"{value:,.4f}".rstrip("0").rstrip(".")
        return text if text not in {"", "-"} else "0"
    if isinstance(value, (list, tuple, set)):
        return html.escape("、".join(str(item) for item in value)) or "—"
    return html.escape(str(value))


def _pct(value: Any) -> str:
    """Format a known ratio field as a percentage."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "—"
    return f"{float(value) * 100:.1f}%"


def _badge(value: Any) -> str:
    slug = (
        str(value or "unknown")
        .lower()
        .replace("_", "-")
        .replace(" ", "-")
    )
    return f'<span class="badge {html.escape(slug)}">{_e(value)}</span>'


def render_section(payload: dict[str, Any]) -> str:
    rows = payload.get("rows") or []
    count = payload.get("readiness_counts") or {}
    cards = "".join(
        f'<article class="card"><div class="card-label">{_e(key)}</div>'
        f'<div class="card-value">{_e(value)}</div>'
        '<div class="card-note">security readiness, not a trade signal</div></article>'
        for key, value in count.items()
    )
    body_rows = []
    for row in rows:
        scenario = row.get("scenario") or {}
        market = row.get("market_context") or {}
        body_rows.append(
            "<tr>"
            f'<td>{_e(row.get("manual_rank"))}</td>'
            f'<td><strong>{_e(row.get("symbol"))}</strong></td>'
            f'<td>{_badge(row.get("company_thesis_status"))}</td>'
            f'<td>{_badge(row.get("security_readiness"))}</td>'
            f'<td>{_e(row.get("decision_posture"))}<br>'
            f'<span class="muted">{_e(row.get("decision_reason"))}</span></td>'
            f'<td>{_e(market.get("current_price"))}<br>'
            f'<span class="muted">{_e(market.get("as_of"))} · '
            f'{_e(market.get("source"))}</span></td>'
            f'<td>{_pct(market.get("return_1m"))} / '
            f'{_pct(market.get("return_3m"))} / '
            f'{_pct(market.get("return_6m"))}</td>'
            f'<td>{_pct(scenario.get("expected_return_pct"))}<br>'
            f'<span class="muted">D/U '
            f'{_e(scenario.get("downside_upside_ratio"))}</span></td>'
            f'<td>{_e(row.get("screen_score"))}<br>'
            f'<span class="muted">coverage '
            f'{_pct(row.get("screen_coverage"))}</span></td>'
            f'<td>{_e(row.get("correlation_baskets"))}</td>'
            f'<td>{_e(row.get("missing_inputs"))}</td>'
            "</tr>"
        )
    table = (
        '<div class="table-wrap"><table><thead><tr>'
        '<th>Manual</th><th>Symbol</th><th>Company thesis</th>'
        '<th>Security readiness</th><th>Posture / reason</th>'
        '<th>Current / as-of</th><th>1M / 3M / 6M</th>'
        '<th>Scenario EV / skew</th><th>Screen</th>'
        '<th>Correlation baskets</th><th>Blocking gaps</th>'
        "</tr></thead><tbody>"
        + (
            "".join(body_rows)
            if body_rows
            else '<tr><td colspan="11">No decision candidates.</td></tr>'
        )
        + "</tbody></table></div>"
    )
    baskets = payload.get("correlation_baskets") or []
    basket_html = "".join(
        f'<div class="subtheme"><strong>{_e(item.get("basket"))}</strong> · '
        f'{_e(item.get("candidate_count"))} candidates'
        f'<div class="muted">{_e(item.get("symbols"))}</div></div>'
        for item in baskets
    ) or '<div class="empty">No correlation baskets configured.</div>'

    health = payload.get("market_context_health") or {}
    freshness = "stale_degraded" if health.get("stale") else "fresh"
    market_health = (
        '<div class="account-strip">'
        f'<span>Market context <strong>{_badge(health.get("status"))}</strong></span>'
        f'<span>Freshness <strong>{_badge(freshness)}</strong></span>'
        f'<span>Generated <strong>{_e(health.get("generated_at"))}</strong></span>'
        f'<span>Unavailable <strong>{_e(health.get("unavailable_count"))}</strong></span>'
        f'<span>Partial <strong>{_e(health.get("partial_count"))}</strong></span>'
        f'<span>Contract <strong>{_e(health.get("contract"))}</strong></span>'
        "</div>"
    )

    private_risk = payload.get("portfolio_decision_risk") or {}
    risk_status = str(private_risk.get("status") or "analysis_unavailable")
    if risk_status in {"ok", "degraded_market_data"}:
        rolls = private_risk.get("roll_window_counts") or {}
        portfolio_health = (
            '<div class="account-strip">'
            f'<span>Decision-risk <strong>{_badge(risk_status)}</strong></span>'
            f'<span>Thesis ID gaps <strong>'
            f'{_e(private_risk.get("missing_thesis_id_count"))}</strong></span>'
            f'<span>Unmapped positions <strong>'
            f'{_e(private_risk.get("unmapped_position_count"))}</strong></span>'
            f'<span>Max basket gross weight <strong>'
            f'{_pct(private_risk.get("max_basket_gross_weight"))}</strong></span>'
            f'<span>Protective Δ coverage <strong>'
            f'{_pct(private_risk.get("hedge_coverage_ratio"))}</strong></span>'
            f'<span>Δ offset <strong>'
            f'{_pct(private_risk.get("delta_offset_ratio"))}</strong></span>'
            f'<span>Roll ≤90/180/270d <strong>'
            f'{_e(rolls.get("dte_le_90"))}/'
            f'{_e(rolls.get("dte_le_180"))}/'
            f'{_e(rolls.get("dte_le_270"))}</strong></span>'
            f'<span>Flags <strong>{_e(private_risk.get("review_flags"))}</strong></span>'
            "</div>"
        )
    else:
        # Never render a failed/skipped analysis as clean zero-gap counts.
        portfolio_health = (
            '<div class="account-strip">'
            f'<span>Decision-risk <strong>{_badge(risk_status)}</strong></span>'
            '<span class="muted">Aggregate decision-risk metrics are '
            'unavailable for this snapshot; treat gaps as unknown, '
            'not zero.</span>'
            "</div>"
        )

    log = payload.get("decision_log") or {}
    calibration = (
        '<div class="account-strip">'
        f'<span>Decisions <strong>{_e(log.get("decision_count"))}</strong></span>'
        f'<span>Resolved <strong>{_e(log.get("resolved_count"))}</strong></span>'
        f'<span>Calibrated forecasts <strong>'
        f'{_e(log.get("calibrated_forecast_count"))}</strong></span>'
        f'<span>Brier score <strong>{_e(log.get("brier_score"))}</strong></span>'
        f'<span>Status <strong>{_badge(log.get("status"))}</strong></span>'
        "</div>"
    )
    return (
        START
        + '<section id="decision"><div class="section-head">'
        '<h2>Decision readiness & scenario skew</h2>'
        '<p>Company thesis, security readiness and action posture are separate. '
        'Missing valuation/evidence remains a blocker.</p></div>'
        + market_health
        + f'<div class="cards">{cards}</div>{table}'
        + '<h3>Correlated research baskets</h3>'
        + f'<div class="theme-card">{basket_html}</div>'
        + '<h3>Private portfolio decision-risk health</h3>'
        + portfolio_health
        + '<div class="privacy-note">Only aggregate counts/ratios are public; '
        'symbols, basket names, contracts and account values remain private.</div>'
        + '<h3>Decision calibration</h3>'
        + calibration
        + '<div class="privacy-note">Append-only decision history. Fewer than '
        '10 resolved probability forecasts is explicitly insufficient for '
        'calibration. No automatic orders.</div>'
        + "</section>"
        + END
    )


def _remove_existing(index: str) -> str:
    if START not in index or END not in index:
        return index
    before, rest = index.split(START, 1)
    _, after = rest.split(END, 1)
    return before + after


def build_decision_layer(output_dir: Path | str) -> dict[str, Any]:
    output = Path(output_dir)
    data_dir = output / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    payload = build_from_store()
    (data_dir / "decision_engine.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    index_path = output / "index.html"
    if not index_path.exists():
        raise FileNotFoundError(f"Mission Control index missing: {index_path}")
    index = _remove_existing(index_path.read_text(encoding="utf-8"))
    index = index.replace(
        '<nav><a href="#attention">',
        '<nav><a href="#decision">Decision</a><a href="#attention">',
        1,
    )
    marker = '<section id="positions">'
    if marker not in index:
        raise ValueError("Mission Control positions marker missing")
    index = index.replace(marker, render_section(payload) + marker, 1)
    index_path.write_text(index, encoding="utf-8")
    return payload
