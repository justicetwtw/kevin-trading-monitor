import json
from pathlib import Path

from src.dashboard import apply_decision_quality as overlay
from src.dashboard import build_decision_layer as layer


def test_dashboard_overlay_downgrades_unapproved_review_ready_row(
    tmp_path: Path,
    monkeypatch,
):
    output = tmp_path / "dashboard"
    (output / "data").mkdir(parents=True)
    payload = {
        "rows": [
            {
                "symbol": "MU",
                "manual_rank": 1,
                "security_readiness": "review_ready",
                "decision_posture": "eligible_for_capital_review",
                "decision_reason": "complete",
                "scenario": {
                    "expected_return_pct": 0.2,
                    "approval_status": "draft_for_kevin_confirmation",
                },
                "market_context": {
                    "status": "healthy",
                    "as_of": "2026-07-16",
                },
                "evidence_as_of": "2026-07-01",
                "next_catalyst": {"date": "2026-08-01"},
                "missing_inputs": [],
            }
        ],
        "readiness_counts": {"review_ready": 1},
        "correlation_baskets": [],
        "decision_log": {"status": "insufficient_history"},
    }
    (output / "index.html").write_text(
        "<html><body>"
        + layer.render_section(payload)
        + "</body></html>",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        overlay,
        "read_json",
        lambda *args, **kwargs: {
            "candidates": [
                {
                    "symbol": "MU",
                    "decision_inputs": {
                        "threshold_origin": "approved_by_kevin"
                    },
                }
            ]
        },
    )

    result = overlay.apply_decision_quality(output, payload)

    assert result["rows"][0]["security_readiness"] == "screen_grade"
    assert "scenario_approval_required" in result["rows"][0]["missing_inputs"]
    saved = json.loads(
        (output / "data/decision_engine.json").read_text(encoding="utf-8")
    )
    assert saved["readiness_counts"] == {"screen_grade": 1}
    html = (output / "index.html").read_text(encoding="utf-8")
    assert "scenario-approval-required" not in html
    assert "scenario_approval_required" in html
    assert html.count(layer.START) == 1
