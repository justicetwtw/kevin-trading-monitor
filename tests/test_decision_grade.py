from src.decision.decision_grade import apply_quality_gates


def _row():
    return {
        "symbol": "MU",
        "manual_rank": 1,
        "security_readiness": "review_ready",
        "decision_posture": "eligible_for_capital_review",
        "decision_reason": "complete",
        "scenario": {
            "expected_return_pct": 0.2,
            "approval_status": "approved_by_kevin",
        },
        "market_context": {
            "status": "healthy",
            "as_of": "2026-07-16",
        },
        "evidence_as_of": "2026-07-01",
        "next_catalyst": {"date": "2026-08-01"},
        "missing_inputs": [],
    }


def _allocation(
    *,
    threshold_origin="approved_by_kevin",
):
    return {
        "candidates": [
            {
                "symbol": "MU",
                "decision_inputs": {
                    "threshold_origin": threshold_origin,
                },
            }
        ]
    }


def test_approved_fresh_row_remains_review_ready():
    payload = {"rows": [_row()], "readiness_counts": {"review_ready": 1}}
    result = apply_quality_gates(payload, _allocation())
    assert result["rows"][0]["security_readiness"] == "review_ready"
    assert result["readiness_counts"] == {"review_ready": 1}


def test_unapproved_scenario_is_screen_only():
    row = _row()
    row["scenario"]["approval_status"] = "draft_for_kevin_confirmation"
    result = apply_quality_gates({"rows": [row]}, _allocation())
    assert result["rows"][0]["security_readiness"] == "screen_grade"
    assert "scenario_approval_required" in result["rows"][0]["missing_inputs"]


def test_unapproved_threshold_origin_is_screen_only():
    result = apply_quality_gates(
        {"rows": [_row()]},
        _allocation(threshold_origin="repo_default_pending_kevin_confirmation"),
    )
    assert result["rows"][0]["security_readiness"] == "screen_grade"
    assert "threshold_origin_unapproved" in result["rows"][0]["missing_inputs"]


def test_stale_evidence_is_screen_only():
    row = _row()
    row["evidence_as_of"] = "2026-05-01"
    result = apply_quality_gates({"rows": [row]}, _allocation())
    assert result["rows"][0]["security_readiness"] == "screen_grade"
    assert "evidence_stale_vs_market" in result["rows"][0]["missing_inputs"]


def test_partial_market_context_and_expired_catalyst_are_screen_only():
    row = _row()
    row["market_context"]["status"] = "partial"
    row["next_catalyst"]["date"] = "2026-07-16"
    result = apply_quality_gates({"rows": [row]}, _allocation())
    gated = result["rows"][0]
    assert gated["security_readiness"] == "screen_grade"
    assert "market_context_partial" in gated["missing_inputs"]
    assert "catalyst_not_future" in gated["missing_inputs"]


def test_existing_not_decision_grade_is_not_promoted():
    row = _row()
    row["security_readiness"] = "not_decision_grade"
    row["scenario"] = None
    result = apply_quality_gates({"rows": [row]}, _allocation())
    assert result["rows"][0]["security_readiness"] == "not_decision_grade"
