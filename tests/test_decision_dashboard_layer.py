import json
from pathlib import Path

from src.dashboard import build_decision_layer as layer


def _payload():
    return {
        "readiness_counts": {"not_decision_grade": 1},
        "rows": [
            {
                "manual_rank": 1,
                "symbol": "MU",
                "company_thesis_status": "active",
                "security_readiness": "not_decision_grade",
                "decision_posture": "wait_for_proof",
                "decision_reason": "scenario required",
                "market_context": {"current_price": 100, "as_of": "2026-07-16", "source": "test"},
                "scenario": None,
                "screen_score": None,
                "screen_coverage": 0.6,
                "correlation_baskets": ["ai_capex", "hbm"],
                "missing_inputs": ["scenario_missing"],
            }
        ],
        "correlation_baskets": [
            {"basket": "ai_capex", "symbols": ["MU"], "candidate_count": 1}
        ],
        "decision_log": {
            "decision_count": 0,
            "resolved_count": 0,
            "calibrated_forecast_count": 0,
            "brier_score": None,
            "status": "insufficient_history",
        },
    }


def test_build_decision_layer_injects_nav_section_and_json(tmp_path: Path, monkeypatch):
    output = tmp_path / "dashboard"
    output.mkdir()
    (output / "index.html").write_text(
        '<html><body><nav><a href="#attention">Attention</a></nav><main><section id="positions">positions</section></main></body></html>',
        encoding="utf-8",
    )
    monkeypatch.setattr(layer, "build_from_store", _payload)
    payload = layer.build_decision_layer(output)
    html = (output / "index.html").read_text(encoding="utf-8")
    saved = json.loads((output / "data/decision_engine.json").read_text(encoding="utf-8"))
    assert payload == _payload()
    assert saved["rows"][0]["symbol"] == "MU"
    assert '<a href="#decision">Decision</a>' in html
    assert 'id="decision"' in html
    assert html.index('id="decision"') < html.index('id="positions"')


def test_injection_is_idempotent(tmp_path: Path, monkeypatch):
    output = tmp_path / "dashboard"
    output.mkdir()
    (output / "index.html").write_text(
        '<html><body><nav><a href="#attention">Attention</a></nav><main><section id="positions">positions</section></main></body></html>',
        encoding="utf-8",
    )
    monkeypatch.setattr(layer, "build_from_store", _payload)
    layer.build_decision_layer(output)
    layer.build_decision_layer(output)
    html = (output / "index.html").read_text(encoding="utf-8")
    assert html.count(layer.START) == 1
    assert html.count('href="#decision"') == 1
