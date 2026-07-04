"""靜態 dashboard 產生器:data_store/ state → public/dashboard/{index.html, data/*.json}。

用法:
    python -m src.dashboard.build_dashboard [--output public/dashboard]

原則:
- 純讀 data_store/,不打外部 API,不需要任何 secret。
- 所有 payload 先過 src/models/signal_schema.py 驗證再落地。
- HTML 只是 JSON 的呈現層;Phase 2 互動前端(Streamlit/Dash)讀同一份 JSON。
"""

import argparse
import html
import json
from pathlib import Path
from string import Template

from loguru import logger

from src.models import signal_schema as schema
from src.storage import dashboard_store as store

TEMPLATE_PATH = Path(__file__).parent / "templates" / "dashboard_page.html"
CSS_PATH = Path(__file__).parent / "static" / "dashboard.css"
DEFAULT_OUTPUT = Path(__file__).parent.parent.parent / "public" / "dashboard"

PAYLOAD_BUILDERS = {
    "regime": store.build_regime_payload,
    "watchlist_scores": store.build_watchlist_scores,
    "options_flow": store.build_options_flow,
    "leaps_exposure": store.build_leaps_exposure,
    "events": store.build_events,
    "decision_log": store.build_decision_log,
}


def _validate_payload(name: str, payload: dict) -> list[str]:
    errors = schema.validate_record(payload, schema.ENVELOPE_SPEC, name)
    data = payload.get("data")
    if not isinstance(data, dict):
        return errors
    if name == "watchlist_scores":
        for i, row in enumerate(data.get("rows", [])):
            errors.extend(schema.validate_watchlist_row(row, f"{name}.rows[{i}]"))
    elif name == "options_flow":
        for i, row in enumerate(data.get("rows", [])):
            errors.extend(schema.validate_record(
                row, schema.OPTIONS_FLOW_ROW_SPEC, f"{name}.rows[{i}]"))
    elif name == "leaps_exposure":
        for i, row in enumerate(data.get("positions", [])):
            errors.extend(schema.validate_record(
                row, schema.LEAPS_POSITION_SPEC, f"{name}.positions[{i}]"))
    elif name == "events":
        for i, row in enumerate(data.get("alerts", [])):
            errors.extend(schema.validate_record(
                row, schema.EVENT_ROW_SPEC, f"{name}.alerts[{i}]"))
    elif name == "decision_log":
        for i, row in enumerate(data.get("entries", [])):
            errors.extend(schema.validate_record(
                row, schema.DECISION_LOG_SPEC, f"{name}.entries[{i}]"))
    return errors


def build_payloads() -> dict:
    """建立並驗證全部 payload;schema 不合直接 raise,不落地壞資料。"""
    payloads = {}
    all_errors = []
    for name, builder in PAYLOAD_BUILDERS.items():
        payload = builder()
        errs = _validate_payload(name, payload)
        if errs:
            all_errors.extend(errs)
        payloads[name] = payload
    if all_errors:
        raise ValueError("dashboard payload schema errors:\n" + "\n".join(all_errors))
    return payloads


# ============================================
# HTML rendering
# ============================================

def _esc(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "✓" if v else "✗"
    if isinstance(v, float):
        return f"{v:g}"
    return html.escape(str(v))


def _table(rows: list[dict], columns: list[tuple[str, str]]) -> str:
    if not rows:
        return '<p class="placeholder">（無資料）</p>'
    head = "".join(f"<th>{html.escape(label)}</th>" for _, label in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{_esc(r.get(key))}</td>" for key, _ in columns) + "</tr>"
        for r in rows
    )
    return (f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table></div>")


def _regime_badge(regime) -> str:
    cls = regime if regime in ("risk_on", "neutral", "risk_off") else "neutral"
    return f'<span class="badge {cls}">{_esc(regime)}</span>'


def _section_regime(payload: dict) -> str:
    d = payload["data"]
    ind_rows = [
        {"indicator": k, "value": v.get("value"), "regime": v.get("regime")}
        for k, v in (d.get("indicators") or {}).items()
    ]
    sub_rows = [
        {"submodule": k, "regime": v.get("regime"), "modifier": v.get("modifier")}
        for k, v in (d.get("submodules") or {}).items()
    ]
    return (
        f'<section id="regime"><h2>1. Regime Overview {_regime_badge(d.get("regime"))}</h2>'
        f'<p>Layer 0 modifier: <strong>{_esc(d.get("modifier"))}</strong>'
        f'<span class="muted">(scan: {_esc(d.get("layer0_scan_time"))})</span></p>'
        + _table(ind_rows, [("indicator", "指標"), ("value", "值"), ("regime", "Regime")])
        + "<h2 class=\"muted\">子模組</h2>"
        + _table(sub_rows, [("submodule", "子模組"), ("regime", "Regime"),
                            ("modifier", "Modifier")])
        + "</section>"
    )


def _section_watchlist(payload: dict) -> str:
    d = payload["data"]
    rows = []
    for r in d.get("rows", []):
        p = r["pillars"]
        rows.append({
            "symbol": r["symbol"],
            "tier": r["tier"],
            "fund": p["fundamental_catalyst"]["score"],
            "trend": p["trend_momentum"]["score"],
            "opt": p["options_flow"]["score"],
            "val": p["valuation_expectation"]["score"],
            "risk": p["risk_macro_geopolitical"]["score"],
            "total": r["total_score"],
            "coverage": r["coverage"],
            "band": r["action_band"],
        })
    cols = [("symbol", "Symbol"), ("tier", "Tier"),
            ("fund", "Fund/催化 (35)"), ("trend", "Trend/動能 (20)"),
            ("opt", "Options/Flow (20)"), ("val", "估值 (10)"),
            ("risk", "Risk/宏觀/地緣 (15)"), ("total", "Total (100)"),
            ("coverage", "Coverage"), ("band", "行動區間")]
    return (
        '<section id="watchlist"><h2>2. Watchlist Score Table</h2>'
        f'<p class="disclaimer">{html.escape(d.get("disclaimer", ""))} '
        "「—」= 資料未接(不用假設值補分);total 只在五 pillar 齊備時計算。</p>"
        + _table(rows, cols) + "</section>"
    )


def _section_options(payload: dict) -> str:
    d = payload["data"]
    cols = [("symbol", "Symbol"), ("ivr", "IVR"), ("ivp", "IVP"),
            ("current_iv", "IV"), ("samples", "樣本數"),
            ("put_skew", "Put Skew"), ("status", "狀態")]
    return (
        '<section id="options"><h2>3. Options / Flow Dashboard</h2>'
        + _table(d.get("rows", []), cols)
        + f'<p class="muted">{html.escape(d.get("paid_data_note", ""))}</p>'
        + "</section>"
    )


def _section_leaps(payload: dict) -> str:
    d = payload["data"]
    t = d.get("totals", {})
    cols = [("id", "ID"), ("symbol", "Symbol"), ("type", "Type"),
            ("strike", "Strike"), ("expiry", "Expiry"), ("dte", "DTE"),
            ("contracts", "口數"), ("cost_per_contract", "成本/股"),
            ("roll_warning", "Roll 警示"), ("equivalent_exposure", "等效曝險"),
            ("status", "狀態")]
    return (
        '<section id="leaps"><h2>4. LEAPS Exposure Dashboard</h2>'
        + _table(d.get("positions", []), cols)
        + f'<p class="muted">部位數 {_esc(t.get("position_count"))} ・ '
          f'名目成本 {_esc(t.get("total_premium_at_cost"))} ・ '
          f'delta/theta/vega 待接 live pricing(Phase 1.1)・ '
          f'Roll 警示門檻 DTE &lt; {_esc(d.get("roll_warning_dte_days"))} 天</p>'
        + "</section>"
    )


def _section_events(payload: dict) -> str:
    d = payload["data"]
    alert_cols = [("timestamp", "時間"), ("source", "來源"), ("symbol", "Symbol"),
                  ("priority", "P"), ("title", "內容"), ("routed_to", "路由")]
    earn_cols = [("symbol", "Symbol"), ("earnings_date", "財報日")]
    return (
        '<section id="events"><h2>5. Event Monitor</h2>'
        "<h2 class=\"muted\">近期訊號(dashboard 保存全部;Telegram 只推 P0/P1)</h2>"
        + _table(list(reversed(d.get("alerts", [])))[:50], alert_cols)
        + "<h2 class=\"muted\">財報日曆</h2>"
        + _table(d.get("earnings_calendar", [])[:30], earn_cols)
        + "</section>"
    )


def _section_taiwan(regime_payload: dict) -> str:
    geo = regime_payload["data"].get("taiwan_geopolitical", {})
    return (
        '<section id="taiwan"><h2>6. Taiwan / Geopolitical Risk</h2>'
        f'<p>台海風險分級(1–10):<strong>{_esc(geo.get("level"))}</strong> '
        f'<span class="muted">({_esc(geo.get("status"))})</span></p>'
        '<p class="placeholder">Phase 2 接結構化資料源前不填分級;'
        "分級規則見 docs/strategy_v4.md §9(直接影響 sizing)。</p></section>"
    )


def _section_backtest() -> str:
    return (
        '<section id="backtest"><h2>7. Backtest / EV Tracker</h2>'
        '<p class="placeholder">Phase 3(vectorbt)接入後填充:EV、最大回撤、'
        "持倉時間、資金效率、vs buy-and-hold / momentum baseline。</p></section>"
    )


def _section_decisions(payload: dict) -> str:
    d = payload["data"]
    cols = [("date", "日期"), ("symbol", "Symbol"), ("action", "動作"),
            ("thesis", "理由"), ("invalidation", "失效條件"),
            ("result", "結果"), ("followed_rules", "守規則"),
            ("review_notes", "檢討")]
    return (
        '<section id="decisions"><h2>8. Decision Log / Review Loop</h2>'
        + _table(d.get("entries", []), cols)
        + f'<p class="muted">{html.escape(d.get("note", ""))}</p></section>'
    )


def render_html(payloads: dict) -> str:
    sections = "\n".join([
        _section_regime(payloads["regime"]),
        _section_watchlist(payloads["watchlist_scores"]),
        _section_options(payloads["options_flow"]),
        _section_leaps(payloads["leaps_exposure"]),
        _section_events(payloads["events"]),
        _section_taiwan(payloads["regime"]),
        _section_backtest(),
        _section_decisions(payloads["decision_log"]),
    ])
    template = Template(TEMPLATE_PATH.read_text(encoding="utf-8"))
    return template.substitute(
        css=CSS_PATH.read_text(encoding="utf-8"),
        generated_at=html.escape(payloads["regime"]["generated_at"]),
        sections=sections,
    )


def build_all(output_dir: Path | str = DEFAULT_OUTPUT) -> dict:
    """產生全部 JSON + HTML;回傳 payload dict 供測試/呼叫方使用。"""
    output_dir = Path(output_dir)
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    payloads = build_payloads()
    for name, payload in payloads.items():
        path = data_dir / f"{name}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        logger.info(f"wrote {path}")

    index = output_dir / "index.html"
    index.write_text(render_html(payloads), encoding="utf-8")
    logger.info(f"wrote {index}")
    return payloads


def main() -> None:
    parser = argparse.ArgumentParser(description="Build static dashboard")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT),
                        help="輸出目錄(預設 public/dashboard)")
    args = parser.parse_args()
    build_all(args.output)


if __name__ == "__main__":
    main()
