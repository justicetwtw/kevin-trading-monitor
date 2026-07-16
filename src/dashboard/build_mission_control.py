"""Build the thesis-first Trading Mission Control static dashboard.

Legacy dashboard JSON remains available for compatibility. The HTML first
screen prioritizes exceptions, themes, thesis health and allocation context.
Public output never includes exact positions, costs, strikes or account value.
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
    return html.escape(str(value))


def _badge(value: Any, extra: str = "") -> str:
    text = _e(value)
    slug = str(value or "unknown").lower().replace("_", "-").replace(" ", "-")
    return (
        f'<span class="badge {html.escape(slug)} {html.escape(extra)}">'
        f"{text}</span>"
    )


def _table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> str:
    if not rows:
        return '<div class="empty">No data yet.</div>'
    head = "".join(f"<th>{html.escape(label)}</th>" for _, label in columns)
    body = []
    for row in rows:
        cells = "".join(f"<td>{_e(row.get(key))}</td>" for key, _ in columns)
        body.append(f"<tr>{cells}</tr>")
    return (
        '<div class="table-wrap"><table><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def _summary_cards(data: dict[str, Any]) -> str:
    summary = data["summary"]
    configured = bool(summary.get("position_configured"))
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
            "Private position state",
            "Configured" if configured else "Not configured",
            (
                f"{_e(summary.get('position_count'))} positions; exact details stay private"
                if configured
                else "Secure runtime input is still missing"
            ),
        ),
        (
            "Tracked theses",
            _e(summary.get("tracked_thesis_count")),
            f"{_e(summary.get('tracked_theme_count'))} themes",
        ),
        (
            "Allocation queue",
            _e(summary.get("allocation_candidate_count")),
            "Manual attention order, not an order list",
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
            f'<div>{_badge(item.get("severity"), "severity")}</div>'
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


def _theme_section(data: dict[str, Any]) -> str:
    themes = data.get("themes", [])
    if not themes:
        return (
            '<section id="themes"><div class="section-head"><h2>Theme map</h2>'
            '</div><div class="empty">No themes configured.</div></section>'
        )
    cards = []
    for theme in themes:
        sub_html = "".join(
            '<div class="subtheme">'
            f'<div><strong>{_e(sub.get("name"))}</strong> '
            f'{_badge(sub.get("status"))}</div>'
            f'<div class="muted">{_e(", ".join(sub.get("symbols") or []))}</div>'
            f'<div>{_e(sub.get("monitor"))}</div>'
            "</div>"
            for sub in (theme.get("subthemes") or [])
            if isinstance(sub, dict)
        )
        cards.append(
            '<article class="theme-card">'
            '<div class="theme-title">'
            f'<h3>{_e(theme.get("name"))}</h3>{_badge(theme.get("status"))}'
            "</div>"
            f'<p>{_e(theme.get("summary"))}</p>{sub_html}'
            f'<div class="review-date">Next review: '
            f'{_e(theme.get("next_review"))}</div>'
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
        '<p>Attention order joined with available state; never an order.</p></div>'
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
    configured = bool(account.get("configured"))
    strip = (
        '<div class="account-strip">'
        f'<span>Mode <strong>{_e(account.get("mode"))}</strong></span>'
        f'<span>Configured <strong>{_e(configured)}</strong></span>'
        f'<span>Position count <strong>{_e(account.get("position_count"))}</strong></span>'
        f'<span>Long options <strong>{_e(account.get("n_long_options"))}</strong></span>'
        f'<span>Short options <strong>{_e(account.get("n_short_options"))}</strong></span>'
        f'<span>Snapshot <strong>{_e(account.get("snapshot_at"))}</strong></span>'
        "</div>"
    )
    privacy = (
        '<div class="privacy-note"><strong>Privacy boundary:</strong> exact symbols, '
        "strikes, costs and account value are intentionally excluded from the public "
        f'dashboard. State: {_e(account.get("privacy"))}.</div>'
    )
    return (
        '<section id="positions"><div class="section-head">'
        '<h2>Portfolio workflow health</h2>'
        '<p>Public status only; detailed exposure remains private.</p></div>'
        + strip
        + privacy
        + "</section>"
    )


def _theses_section(data: dict[str, Any]) -> str:
    rows = []
    for thesis in data.get("theses", []):
        rows.append({
            "symbol": thesis.get("symbol"),
            "theme": thesis.get("theme"),
            "status": thesis.get("status"),
            "summary": thesis.get("summary"),
            "catalysts": " · ".join(thesis.get("catalysts") or []),
            "invalidation": " · ".join(thesis.get("invalidation") or []),
            "next_review": thesis.get("next_review"),
        })
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


def _market_context(payloads: dict[str, Any]) -> str:
    options_rows = payloads["options_flow"].get("data", {}).get("rows", [])
    options_rows = [
        row
        for row in options_rows
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
            options_rows,
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
:root{color-scheme:dark;--bg:#090b10;--panel:#11151d;--panel2:#171c26;--line:#293140;--text:#f5f7fb;--muted:#9aa6b6;--accent:#8ab4ff;--red:#ff6b7a;--amber:#ffc857;--green:#58d68d}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top,#172035 0,#090b10 38%);color:var(--text);font:15px/1.55 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}header{padding:42px max(24px,5vw) 24px;border-bottom:1px solid var(--line)}header h1{font-size:clamp(30px,5vw,58px);letter-spacing:-.045em;margin:0 0 8px}.kicker{color:var(--accent);font-weight:700;text-transform:uppercase;letter-spacing:.14em;font-size:12px}.subtitle{color:var(--muted);max-width:900px}.meta{color:var(--muted);font-size:12px;margin-top:14px}nav{position:sticky;top:0;z-index:5;display:flex;gap:8px;overflow:auto;padding:12px max(24px,5vw);background:rgba(9,11,16,.88);backdrop-filter:blur(18px);border-bottom:1px solid var(--line)}nav a{color:var(--muted);text-decoration:none;padding:7px 11px;border-radius:999px;white-space:nowrap}nav a:hover{color:var(--text);background:var(--panel2)}main{padding:28px max(24px,5vw) 80px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin-bottom:28px}.card,.theme-card,.attention-item,.account-strip,.privacy-note{background:linear-gradient(145deg,rgba(23,28,38,.95),rgba(15,19,27,.95));border:1px solid var(--line);border-radius:18px}.card{padding:18px}.card-label,.card-note,.muted,.attention-meta,.review-date{color:var(--muted)}.card-value{font-size:27px;font-weight:750;margin:8px 0}.card-note{font-size:12px}section{margin:24px 0 38px;scroll-margin-top:80px}.section-head{display:flex;align-items:end;justify-content:space-between;gap:24px;margin-bottom:14px}.section-head h2{font-size:25px;margin:0;letter-spacing:-.02em}.section-head p{margin:0;color:var(--muted);text-align:right}.attention-list{display:grid;gap:10px}.attention-item{display:grid;grid-template-columns:auto 1fr;gap:14px;padding:16px}.attention-title{font-weight:750;font-size:16px}.attention-detail{margin-top:3px}.attention-meta{font-size:12px;margin-top:6px}.badge{display:inline-flex;align-items:center;border:1px solid var(--line);border-radius:999px;padding:3px 8px;font-size:12px;background:#202735}.badge.p0{border-color:rgba(255,107,122,.6);color:var(--red)}.badge.p1{border-color:rgba(255,200,87,.6);color:var(--amber)}.badge.risk-on,.badge.active,.badge.structural-tightness-watch,.badge.cycle-tightness-watch{color:var(--green)}.badge.risk-off,.badge.broken,.badge.invalidated{color:var(--red)}.theme-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}.theme-card{padding:20px}.theme-title{display:flex;align-items:center;justify-content:space-between;gap:12px}.theme-title h3{margin:0;font-size:21px}.subtheme{border-top:1px solid var(--line);padding:12px 0}.review-date{font-size:12px;margin-top:12px}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:16px;background:rgba(17,21,29,.92)}table{width:100%;border-collapse:collapse;min-width:900px}th,td{padding:12px 13px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{position:sticky;top:0;background:#171c26;color:#cbd5e1;font-size:12px;text-transform:uppercase;letter-spacing:.04em}td{max-width:380px}.empty,.ok-state{padding:22px;border:1px dashed var(--line);border-radius:16px;color:var(--muted)}.ok-state{color:var(--green)}.account-strip{display:flex;flex-wrap:wrap;gap:18px;padding:14px 16px}.account-strip span{color:var(--muted)}.account-strip strong{color:var(--text);margin-left:5px}.privacy-note{padding:16px;margin-top:10px;color:var(--muted)}h3{margin-top:22px}@media(max-width:760px){header{padding-top:30px}.section-head{align-items:start;flex-direction:column}.section-head p{text-align:left}.cards{grid-template-columns:1fr}.card-value{font-size:22px}}
"""


def render_html(payloads: dict[str, Any]) -> str:
    mission = payloads["mission_control"]
    data = mission["data"]
    sections = "".join([
        _summary_cards(data),
        _attention_section(data),
        _theme_section(data),
        _allocation_section(data),
        _positions_section(data),
        _theses_section(data),
        _market_context(payloads),
    ])
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kevin Trading Mission Control</title><style>{CSS}</style></head><body>
<header><div class="kicker">Personal capital allocation / thesis monitor</div><h1>Kevin Trading Mission Control</h1>
<div class="subtitle">Exceptions, theses and opportunity context first. Telegram carries urgent alerts; this page keeps the complete public review state.</div>
<div class="meta">generated_at {_e(mission.get('generated_at'))} · repo is the single source of truth · decision support only · no automated trading</div></header>
<nav><a href="#attention">Attention</a><a href="#themes">Themes</a><a href="#allocation">Allocation</a><a href="#positions">Portfolio health</a><a href="#theses">Theses</a><a href="#context">Market context</a></nav>
<main>{sections}<p class="meta">{_e(data.get('disclaimer'))}</p></main></body></html>"""


def build_payloads() -> dict[str, Any]:
    payloads = build_legacy_payloads()
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
