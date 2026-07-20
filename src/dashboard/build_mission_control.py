"""Build the thesis-first public Trading Mission Control dashboard.

Legacy public payloads remain available for compatibility, but all position
payloads are redacted before they are written to `public/dashboard/`. Trump
health shows source and capture policy but never publishes post text.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from loguru import logger

from src.dashboard.build_dashboard import build_payloads as build_legacy_payloads
from src.storage.mission_control_store import build_mission_control_payload

DEFAULT_OUTPUT = Path(__file__).parent.parent.parent / "public" / "dashboard"


def _e(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        return f"{value:,.2f}"
    if isinstance(value, dict):
        return html.escape(
            ", ".join(f"{key}={item}" for key, item in value.items())
        ) or "—"
    if isinstance(value, (list, tuple, set)):
        return html.escape(", ".join(str(item) for item in value)) or "—"
    return html.escape(str(value))


def _badge(value: Any) -> str:
    text = _e(value)
    slug = (
        str(value or "unknown")
        .lower()
        .replace("_", "-")
        .replace(" ", "-")
    )
    return f'<span class="badge {html.escape(slug)}">{text}</span>'


def _table(
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str]],
) -> str:
    if not rows:
        return '<div class="empty">No data yet.</div>'
    head = "".join(
        f"<th>{html.escape(label)}</th>" for _, label in columns
    )
    body = []
    for row in rows:
        cells = "".join(
            f"<td>{_e(row.get(key))}</td>" for key, _ in columns
        )
        body.append(f"<tr>{cells}</tr>")
    return (
        '<div class="table-wrap"><table><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def _summary_cards(data: dict[str, Any]) -> str:
    summary = data.get("summary", {})
    configured = bool(summary.get("position_configured"))
    workflow = summary.get("position_workflow_status") or "unknown"
    trump_status = summary.get("trump_monitor_status") or "unknown"
    trump_source = summary.get("trump_monitor_source") or "no verified source"
    cards = [
        (
            "Market regime",
            _badge(summary.get("regime")),
            f"Modifier {_e(summary.get('regime_modifier'))}",
        ),
        (
            "Needs attention",
            _e(summary.get("needs_attention_count")),
            "P0/P1/P2 review queue",
        ),
        (
            "Private positions",
            "Configured" if configured else "Not configured",
            f"{_e(summary.get('position_count'))} positions · {_e(workflow)}",
        ),
        (
            "Trump capture",
            _badge(trump_status),
            f"source: {_e(trump_source)}",
        ),
        (
            "Tracked theses",
            _e(summary.get("tracked_thesis_count")),
            f"{_e(summary.get('tracked_theme_count'))} themes",
        ),
        (
            "Allocation queue",
            _e(summary.get("allocation_candidate_count")),
            "Attention order, not an order list",
        ),
    ]
    return '<div class="cards">' + "".join(
        '<article class="card">'
        f'<div class="card-label">{html.escape(label)}</div>'
        f'<div class="card-value">{value}</div>'
        f'<div class="card-note">{note}</div>'
        "</article>"
        for label, value, note in cards
    ) + "</div>"


def _attention_section(data: dict[str, Any]) -> str:
    items = data.get("attention", [])
    if not items:
        content = '<div class="ok-state">No P0/P1/P2 items detected.</div>'
    else:
        content = '<div class="attention-list">' + "".join(
            '<article class="attention-item">'
            f'<div>{_badge(item.get("severity"))}</div>'
            '<div class="attention-copy">'
            f'<div class="attention-title">{_e(item.get("title"))}</div>'
            f'<div class="attention-detail">{_e(item.get("detail"))}</div>'
            f'<div class="attention-meta">{_e(item.get("category"))} · '
            f'{_e(item.get("symbol"))}</div>'
            "</div></article>"
            for item in items
        ) + "</div>"
    return (
        '<section id="attention"><div class="section-head">'
        '<h2>Needs attention</h2>'
        '<p>Exceptions first, not a wall of normal states.</p>'
        f"</div>{content}</section>"
    )


def _trump_section(data: dict[str, Any]) -> str:
    state = data.get("trump_monitor", {})
    attempts = [
        item for item in (state.get("attempts") or [])
        if isinstance(item, dict)
    ]
    strip = (
        '<div class="account-strip">'
        f'<span>Status <strong>{_badge(state.get("status"))}</strong></span>'
        f'<span>Current source <strong>{_e(state.get("source"))}</strong></span>'
        f'<span>Latest post <strong>{_e(state.get("latest_post_at"))}</strong></span>'
        f'<span>Last check <strong>{_e(state.get("checked_at"))}</strong></span>'
        f'<span>Health age <strong>{_e(state.get("health_age_hours"))}h</strong></span>'
        f'<span>Delivery <strong>{_e(state.get("delivery_status"))}</strong></span>'
        "</div>"
    )
    policy = (
        '<div class="privacy-note">'
        '<strong>Capture contract:</strong> '
        f'{_e(state.get("capture_policy"))}. '
        '<strong>Keyword contract:</strong> '
        f'{_e(state.get("keyword_policy"))}. '
        'Tier determines urgency only; it must not suppress a post. '
        f'Initial backfill: {_e(state.get("initial_backfill_hours"))} hours; '
        f'capture checkpoint: {_e(state.get("capture_started_at"))}.'
        "</div>"
    )
    counts = (
        '<div class="account-strip">'
        f'<span>Source raw <strong>{_e(state.get("source_raw_count"))}</strong></span>'
        f'<span>Bounded window <strong>{_e(state.get("source_returned_count"))}/'
        f'{_e(state.get("source_limit"))}</strong></span>'
        f'<span>Eligible <strong>{_e(state.get("eligible_count"))}</strong></span>'
        f'<span>New <strong>{_e(state.get("new_count"))}</strong></span>'
        f'<span>Delivered <strong>{_e(state.get("delivered_count"))}</strong></span>'
        "</div>"
    )
    attempts_html = _table(
        attempts,
        [
            ("source", "Attempted source"),
            ("status", "Status"),
            ("latest_post_at", "Latest post"),
            ("raw_count", "Raw rows"),
            ("returned_count", "Bounded rows"),
            ("error", "Error"),
        ],
    )
    return (
        '<section id="trump"><div class="section-head">'
        '<h2>Trump Truth Social source health</h2>'
        '<p>Source honesty and all-post capture policy; post text stays in the archive and Telegram.</p>'
        "</div>"
        + strip
        + counts
        + policy
        + '<h3>Source attempts</h3>'
        + attempts_html
        + "</section>"
    )


def _theme_section(data: dict[str, Any]) -> str:
    themes = data.get("themes", [])
    if not themes:
        return (
            '<section id="themes"><div class="section-head"><h2>Theme map</h2>'
            '</div><div class="empty">No themes configured.</div></section>'
        )
    cards = []
    for theme in themes:
        subthemes = "".join(
            '<div class="subtheme">'
            f'<div><strong>{_e(item.get("name"))}</strong> '
            f'{_badge(item.get("status"))}</div>'
            f'<div class="muted">{_e(item.get("symbols") or [])}</div>'
            f'<div>{_e(item.get("monitor"))}</div>'
            "</div>"
            for item in (theme.get("subthemes") or [])
            if isinstance(item, dict)
        )
        cards.append(
            '<article class="theme-card">'
            '<div class="theme-title">'
            f'<h3>{_e(theme.get("name"))}</h3>{_badge(theme.get("status"))}'
            "</div>"
            f'<p>{_e(theme.get("summary"))}</p>{subthemes}'
            f'<div class="muted">Next review: {_e(theme.get("next_review"))}</div>'
            "</article>"
        )
    return (
        '<section id="themes"><div class="section-head"><h2>Theme map</h2>'
        '<p>Industry first; symbols are expressions of the thesis.</p></div>'
        '<div class="theme-grid">'
        + "".join(cards)
        + "</div></section>"
    )


def _allocation_section(data: dict[str, Any]) -> str:
    return (
        '<section id="allocation"><div class="section-head">'
        '<h2>Capital allocation queue</h2>'
        '<p>Joined with available public state; never an automatic order.</p></div>'
        + _table(
            data.get("allocation_queue", []),
            [
                ("manual_rank", "Rank"),
                ("symbol", "Symbol"),
                ("theme", "Theme"),
                ("subtheme", "Subtheme"),
                ("status", "Status"),
                ("preferred_instrument", "Instrument lens"),
                ("total_score", "Score"),
                ("coverage", "Coverage"),
                ("ivr", "IVR"),
                ("ivp", "IVP"),
                ("trigger", "Review trigger"),
                ("invalidation", "Invalidation"),
            ],
        )
        + "</section>"
    )


def _positions_section(data: dict[str, Any]) -> str:
    account = data.get("account", {})
    strip = (
        '<div class="account-strip">'
        f'<span>Mode <strong>{_e(account.get("mode"))}</strong></span>'
        f'<span>Source <strong>{_e(account.get("position_source"))}</strong></span>'
        f'<span>Workflow <strong>{_e(account.get("workflow_status"))}</strong></span>'
        f'<span>Configured <strong>{_e(account.get("configured"))}</strong></span>'
        f'<span>Positions <strong>{_e(account.get("position_count"))}</strong></span>'
        f'<span>Long/short options <strong>{_e(account.get("n_long_options"))}/'
        f'{_e(account.get("n_short_options"))}</strong></span>'
        f'<span>Drawdown <strong>{_e(account.get("drawdown_pct"))}</strong></span>'
        f'<span>Snapshot <strong>{_e(account.get("snapshot_at"))}</strong></span>'
        "</div>"
    )
    error_codes = account.get("error_codes") or []
    errors = (
        '<div class="privacy-note"><strong>Safe error codes:</strong> '
        f'{_e(error_codes)}</div>'
        if error_codes
        else ""
    )
    privacy = (
        '<div class="privacy-note"><strong>Privacy boundary:</strong> exact symbols, '
        "strikes, expiries, costs, PnL, account value and private Greeks are "
        f'excluded. State: {_e(account.get("privacy"))}.</div>'
    )
    return (
        '<section id="positions"><div class="section-head">'
        '<h2>Portfolio workflow health</h2>'
        '<p>Public health only; detailed risk is delivered privately by Telegram.</p>'
        "</div>"
        + strip
        + errors
        + privacy
        + "</section>"
    )


def _theses_section(data: dict[str, Any]) -> str:
    rows = [
        {
            "symbol": thesis.get("symbol"),
            "theme": thesis.get("theme"),
            "status": thesis.get("status"),
            "summary": thesis.get("summary"),
            "catalysts": " · ".join(thesis.get("catalysts") or []),
            "invalidation": " · ".join(thesis.get("invalidation") or []),
            "next_review": thesis.get("next_review"),
        }
        for thesis in data.get("theses", [])
    ]
    return (
        '<section id="theses"><div class="section-head">'
        '<h2>Symbol thesis tracker</h2>'
        '<p>Catalysts, invalidation and review dates.</p></div>'
        + _table(
            rows,
            [
                ("symbol", "Symbol"),
                ("theme", "Theme"),
                ("status", "Status"),
                ("summary", "Thesis"),
                ("catalysts", "Catalysts"),
                ("invalidation", "Invalidation"),
                ("next_review", "Next review"),
            ],
        )
        + "</section>"
    )


def _focus_section(data: dict[str, Any]) -> str:
    """Render the Focus Trading Engine block (shadow/display-only).

    When the feature flag is off the block honestly shows a disabled state; when
    on it renders Market Regime, Portfolio Exceptions, Theme Rotation and Focus
    Securities with source/readiness blockers visible (contract §8 first screen).
    """
    focus = data.get("focus_engine") or {}
    if not focus.get("enabled"):
        return (
            '<section id="focus"><div class="section-head">'
            "<h2>Focus Engine (shadow)</h2>"
            "<p>Holdings-first thesis/timing/exposure overlay.</p></div>"
            '<div class="ok-state">Focus Engine is disabled '
            "(FOCUS_ENGINE_ENABLED != 1); existing Decision Engine is authoritative."
            "</div></section>"
        )
    fdata = focus.get("data") or {}
    health = focus.get("health") or {}
    regime = fdata.get("market_regime") or {}
    exceptions = fdata.get("portfolio_exceptions") or {}
    rotation = fdata.get("theme_rotation") or {}
    cards = fdata.get("focus_securities") or []

    # 1. Market Regime — VIX complex, freshness, workflow health, blockers visible.
    vol_fresh = (regime.get("freshness") or {}) if isinstance(regime, dict) else {}
    regime_blockers = []
    if not regime:
        regime_blockers.append("market_regime_unavailable")
    if vol_fresh.get("status") in ("stale", "missing"):
        regime_blockers.append(f"volatility_{vol_fresh.get('status')}")
    cap = (regime.get("exposure_cap") or {}) if isinstance(regime, dict) else {}
    composite = (regime.get("composite_regime") or {}) if isinstance(regime, dict) else {}
    mtrend = (regime.get("trend") or {}) if isinstance(regime, dict) else {}
    idx_trend = mtrend.get("index_trend") or {}
    if cap.get("blocks_new_exposure"):
        cap_effect = "blocks new exposure"
    elif cap.get("reduces_new_exposure"):
        cap_effect = "reduces new exposure"
    else:
        cap_effect = "full"
    market_regime_html = (
        "<h3>Market Regime</h3>"
        '<div class="account-strip">'
        f'<span>Workflow <strong>{_badge(health.get("workflow_status"))}</strong></span>'
        f'<span>Error codes <strong>{_e(health.get("error_codes") or [])}</strong></span>'
        f'<span>Composite regime <strong>{_badge(regime.get("regime"))}</strong></span>'
        f'<span>VIX regime <strong>{_badge(composite.get("vix_regime"))}</strong></span>'
        f'<span>Escalated <strong>{_e(composite.get("escalated_from_vix"))}</strong></span>'
        f'<span>VIX <strong>{_e(regime.get("vix"))}</strong></span>'
        f'<span>VIX as-of <strong>{_e(vol_fresh.get("as_of"))}</strong></span>'
        f'<span>Freshness <strong>{_badge(vol_fresh.get("status"))}</strong></span>'
        f'<span>Exposure cap <strong>{_e(cap.get("max_exposure_multiplier"))}</strong> ({cap_effect})</span>'
        f'<span>Term inversion <strong>{_e(regime.get("term_inversion"))}</strong></span>'
        "</div>"
        '<div class="account-strip">'
        f'<span>QQQ &gt;50/200DMA <strong>{_e(idx_trend.get("QQQ", {}).get("above_50dma"))}/'
        f'{_e(idx_trend.get("QQQ", {}).get("above_200dma"))}</strong></span>'
        f'<span>SMH &gt;50/200DMA <strong>{_e(idx_trend.get("SMH", {}).get("above_50dma"))}/'
        f'{_e(idx_trend.get("SMH", {}).get("above_200dma"))}</strong></span>'
        f'<span>SOXX &gt;50/200DMA <strong>{_e(idx_trend.get("SOXX", {}).get("above_50dma"))}/'
        f'{_e(idx_trend.get("SOXX", {}).get("above_200dma"))}</strong></span>'
        f'<span>Breadth &gt;50/200DMA <strong>{_e(mtrend.get("breadth_above_50dma"))}/'
        f'{_e(mtrend.get("breadth_above_200dma"))}</strong></span>'
        "</div>"
        + (
            f'<div class="privacy-note"><strong>Blockers:</strong> {_e(regime_blockers)}. '
            "VVIX/COR1M remain capability gaps (paid source not connected).</div>"
            if regime_blockers
            else '<div class="privacy-note">VVIX/COR1M remain capability gaps '
            "(paid source not connected).</div>"
        )
    )

    # 2. Portfolio Exceptions — aggregate-only private risk (no identifiers).
    portfolio_html = (
        "<h3>Portfolio Exceptions</h3>"
        + (
            '<div class="account-strip">'
            f'<span>Hedge coverage <strong>{_badge(exceptions.get("hedge_coverage_band"))}</strong></span>'
            f'<span>Coverage status <strong>{_e(exceptions.get("hedge_coverage_status"))}</strong></span>'
            f'<span>Max theme concentration <strong>{_badge(exceptions.get("max_theme_concentration_band"))}</strong></span>'
            f'<span>Unmapped risk gap <strong>{_e(exceptions.get("has_unmapped_risk_gap"))}</strong></span>'
            "</div>"
            '<div class="privacy-note">Aggregate bands/counts only; no symbols, '
            "strikes, contracts, costs or account value.</div>"
            if exceptions
            else '<div class="empty">No private position input configured '
            "(aggregate exceptions unavailable).</div>"
        )
    )

    # 3. Theme Rotation — constituents-only proxy with rank/percentile + blockers.
    rotation_rows = rotation.get("rows") or []
    rotation_html = (
        "<h3>Theme Rotation (price-return proxy, not fund flow)</h3>"
        + _table(
            rotation_rows,
            [
                ("theme", "Theme"),
                ("status", "Status"),
                ("basket_kind", "Basket"),
                ("member_coverage", "Coverage"),
                ("as_of", "As of"),
                ("theme_rank", "Rank"),
                ("theme_percentile_rank", "Percentile"),
                ("rs_vs_qqq_20", "RS20 vs QQQ"),
                ("leadership_direction", "Leadership"),
                ("breakout_20d_share", "20D breakout"),
                ("breakout_55d_share", "55D breakout"),
            ],
        )
    )

    # 4. Focus Securities — holdings-first cards with source/as-of/blockers visible.
    focus_html = (
        "<h3>Focus Securities</h3>"
        + _table(
            cards,
            [
                ("symbol", "Symbol"),
                ("company_thesis_state", "Thesis"),
                ("timing_state", "Timing"),
                ("exposure_posture", "Posture"),
                ("add_allowed", "Add ready"),
                ("proposed_size_multiplier", "Size mult"),
                ("rs20_vs_qqq", "RS20"),
                ("valuation_status", "Valuation"),
                ("valuation_decision_grade", "Val OK"),
                ("options_capability_status", "Options"),
                ("readiness_blockers", "Blockers"),
                ("as_of", "As of"),
            ],
        )
    )
    return (
        '<section id="focus"><div class="section-head">'
        "<h2>Focus Engine (shadow)</h2>"
        "<p>Static public focus universe; timing paces exposure, never the thesis. "
        "Not a trade signal.</p></div>"
        + market_regime_html
        + portfolio_html
        + rotation_html
        + focus_html
        + "</section>"
    )


def _market_context(payloads: dict[str, Any]) -> str:
    option_rows = [
        row
        for row in payloads["options_flow"].get("data", {}).get("rows", [])
        if row.get("ivr") is not None or row.get("ivp") is not None
    ]
    events = list(
        reversed(payloads["events"].get("data", {}).get("alerts", []))
    )[:20]
    return (
        '<section id="context"><div class="section-head">'
        '<h2>Market context</h2>'
        '<p>Supporting state; TradingView remains the chart surface.</p></div>'
        '<h3>Options / volatility state</h3>'
        + _table(
            option_rows,
            [
                ("symbol", "Symbol"),
                ("ivr", "IVR"),
                ("ivp", "IVP"),
                ("current_iv", "IV"),
                ("put_skew", "Put skew"),
                ("status", "Status"),
            ],
        )
        + '<h3>Recent routed events</h3>'
        + _table(
            events,
            [
                ("timestamp", "Time"),
                ("priority", "P"),
                ("symbol", "Symbol"),
                ("source", "Source"),
                ("title", "Event"),
                ("routed_to", "Route"),
            ],
        )
        + "</section>"
    )


CSS = """
:root{color-scheme:dark;--bg:#090b10;--panel:#11151d;--panel2:#171c26;--line:#293140;--text:#f5f7fb;--muted:#9aa6b6;--accent:#8ab4ff;--red:#ff6b7a;--amber:#ffc857;--green:#58d68d}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top,#172035 0,#090b10 38%);color:var(--text);font:15px/1.55 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}header{padding:42px max(24px,5vw) 24px;border-bottom:1px solid var(--line)}header h1{font-size:clamp(30px,5vw,58px);letter-spacing:-.045em;margin:0 0 8px}.kicker{color:var(--accent);font-weight:700;text-transform:uppercase;letter-spacing:.14em;font-size:12px}.subtitle{color:var(--muted);max-width:900px}.meta,.muted,.attention-meta{color:var(--muted);font-size:12px}nav{position:sticky;top:0;z-index:5;display:flex;gap:8px;overflow:auto;padding:12px max(24px,5vw);background:rgba(9,11,16,.9);backdrop-filter:blur(18px);border-bottom:1px solid var(--line)}nav a{color:var(--muted);text-decoration:none;padding:7px 11px;border-radius:999px;white-space:nowrap}nav a:hover{color:var(--text);background:var(--panel2)}main{padding:28px max(24px,5vw) 80px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin-bottom:28px}.card,.theme-card,.attention-item,.account-strip,.privacy-note{background:linear-gradient(145deg,rgba(23,28,38,.95),rgba(15,19,27,.95));border:1px solid var(--line);border-radius:18px}.card{padding:18px}.card-label,.card-note{color:var(--muted)}.card-value{font-size:27px;font-weight:750;margin:8px 0}.card-note{font-size:12px}section{margin:24px 0 38px;scroll-margin-top:80px}.section-head{display:flex;align-items:end;justify-content:space-between;gap:24px;margin-bottom:14px}.section-head h2{font-size:25px;margin:0}.section-head p{margin:0;color:var(--muted);text-align:right}.attention-list{display:grid;gap:10px}.attention-item{display:grid;grid-template-columns:auto 1fr;gap:14px;padding:16px}.attention-title{font-weight:750;font-size:16px}.attention-detail{margin-top:3px}.badge{display:inline-flex;border:1px solid var(--line);border-radius:999px;padding:3px 8px;font-size:12px;background:#202735}.badge.p0,.badge.failed,.badge.broken,.badge.unavailable{color:var(--red)}.badge.p1,.badge.degraded,.badge.stale{color:var(--amber)}.badge.active,.badge.healthy,.badge.risk-on{color:var(--green)}.theme-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}.theme-card{padding:20px}.theme-title{display:flex;justify-content:space-between;align-items:center;gap:12px}.theme-title h3{margin:0}.subtheme{border-top:1px solid var(--line);padding:12px 0}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:16px;background:rgba(17,21,29,.92)}table{width:100%;border-collapse:collapse;min-width:900px}th,td{padding:12px 13px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{position:sticky;top:0;background:#171c26;color:#cbd5e1;font-size:12px;text-transform:uppercase}td{max-width:380px}.empty,.ok-state{padding:22px;border:1px dashed var(--line);border-radius:16px;color:var(--muted)}.ok-state{color:var(--green)}.account-strip{display:flex;flex-wrap:wrap;gap:18px;padding:14px 16px;margin-bottom:10px}.account-strip span{color:var(--muted)}.account-strip strong{color:var(--text);margin-left:5px}.privacy-note{padding:16px;margin-top:10px;color:var(--muted)}@media(max-width:760px){.section-head{align-items:start;flex-direction:column}.section-head p{text-align:left}.cards{grid-template-columns:1fr}.card-value{font-size:22px}}
"""


def _redacted_leaps_payload(original: dict[str, Any]) -> dict[str, Any]:
    """Preserve the legacy endpoint without publishing contract details."""
    return {
        "schema_version": original.get("schema_version", 1),
        "generated_at": original.get("generated_at"),
        "source_files": ["position_snapshot.json"],
        "data": {
            "positions": [],
            "status": "redacted_private_positions",
            "privacy": (
                "exact LEAPS exposure is delivered only by private Telegram"
            ),
        },
    }


def render_html(payloads: dict[str, Any]) -> str:
    mission = payloads["mission_control"]
    data = mission["data"]
    sections = "".join(
        [
            _summary_cards(data),
            _attention_section(data),
            _trump_section(data),
            _theme_section(data),
            _allocation_section(data),
            _focus_section(data),
            _positions_section(data),
            _theses_section(data),
            _market_context(payloads),
        ]
    )
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kevin Trading Mission Control</title><style>{CSS}</style></head><body>
<header><div class="kicker">Personal capital allocation / thesis monitor</div><h1>Kevin Trading Mission Control</h1>
<div class="subtitle">Exceptions, source honesty, theses and opportunity context first. Telegram carries urgent alerts, every new Trump post and private portfolio risk.</div>
<div class="meta">generated_at {_e(mission.get('generated_at'))} · repo is the source of truth · decision support only · no automated trading</div></header>
<nav><a href="#attention">Attention</a><a href="#trump">Trump source</a><a href="#themes">Themes</a><a href="#allocation">Allocation</a><a href="#focus">Focus engine</a><a href="#positions">Portfolio health</a><a href="#theses">Theses</a><a href="#context">Market context</a></nav>
<main>{sections}<p class="meta">{_e(data.get('disclaimer'))}</p></main></body></html>"""


def build_payloads() -> dict[str, Any]:
    payloads = build_legacy_payloads()
    payloads["leaps_exposure"] = _redacted_leaps_payload(
        payloads.get("leaps_exposure", {})
    )
    payloads["mission_control"] = build_mission_control_payload()
    return payloads


def build_all(output_dir: Path | str = DEFAULT_OUTPUT) -> dict[str, Any]:
    output_dir = Path(output_dir)
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    payloads = build_payloads()
    for name, payload in payloads.items():
        path = data_dir / f"{name}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"wrote {path}")
    index = output_dir / "index.html"
    index.write_text(render_html(payloads), encoding="utf-8")
    logger.info(f"wrote {index}")
    return payloads


if __name__ == "__main__":
    build_all()
