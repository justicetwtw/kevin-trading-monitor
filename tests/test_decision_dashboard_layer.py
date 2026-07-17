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


def test_ratio_fields_are_not_misprinted_as_percentages():
    """R14: downside/upside ratio, Brier and sub-$1 prices are not percents."""
    payload = _payload()
    payload["rows"][0]["scenario"] = {
        "expected_return_pct": 0.2,
        "downside_upside_ratio": 0.8,
    }
    payload["rows"][0]["market_context"] = {
        "current_price": 0.98,
        "as_of": "2026-07-16",
        "source": "test",
        "return_1m": 0.05,
    }
    payload["decision_log"]["brier_score"] = 0.25
    html = layer.render_section(payload)
    # Ratio and Brier render as plain numbers, never percentages.
    assert "D/U 0.8" in html
    assert "80.0%" not in html
    assert "25.0%" not in html
    assert "0.25" in html
    # Known percentage fields still render as percentages.
    assert "20.0%" in html
    assert "5.0%" in html
    # A sub-$1 price is a price, not 98%.
    assert "0.98" in html
    assert "98.0%" not in html


def test_unavailable_decision_risk_renders_degraded_not_zero(monkeypatch):
    """R6: analysis_unavailable must not render as clean zero-gap counts."""
    payload = _payload()
    payload["portfolio_decision_risk"] = {
        "status": "analysis_unavailable",
        "privacy": "aggregate_decision_risk_only",
    }
    html = layer.render_section(payload)
    assert "analysis-unavailable" in html
    assert "Thesis ID gaps" not in html
    assert "treat gaps as unknown" in html


def test_ok_decision_risk_renders_position_counts(monkeypatch):
    payload = _payload()
    payload["portfolio_decision_risk"] = {
        "status": "ok",
        "missing_thesis_id_count": 1,
        "unmapped_position_count": 2,
        "max_basket_gross_weight": 0.4,
        "hedge_coverage_ratio": 0.1,
        "delta_offset_ratio": 0.3,
        "roll_window_counts": {"dte_le_90": 0, "dte_le_180": 1, "dte_le_270": 1},
        "review_flags": [],
    }
    html = layer.render_section(payload)
    assert "Unmapped positions" in html
    assert "10.0%" in html  # protective coverage
    assert "30.0%" in html  # delta offset


def test_stale_market_context_health_is_flagged(monkeypatch):
    """R2: a frozen snapshot must degrade the health strip."""
    assert layer._market_context_is_stale(None)
    assert layer._market_context_is_stale("not-a-date")
    from datetime import date

    assert layer._market_context_is_stale(
        "2026-07-01T06:20:00+00:00", today=date(2026, 7, 17)
    )
    assert not layer._market_context_is_stale(
        "2026-07-15T06:20:00+00:00", today=date(2026, 7, 17)
    )
    payload = _payload()
    payload["market_context_health"] = {"status": "healthy", "stale": True}
    html = layer.render_section(payload)
    assert "stale-degraded" in html
