from src.decision.opportunity_ranker import (
    assess_candidate,
    build_decision_payload,
    summarize_decision_log,
    validate_scenario,
)


def _scenario(expected_source=True):
    return {
        "current_price": 100,
        "as_of": "2026-07-16",
        "source": "source" if expected_source else "",
        "probability_origin": "analyst_assumption",
        "approval_status": "approved_by_kevin",
        "cases": [
            {"name": "down", "probability": 0.25, "price": 70},
            {"name": "base", "probability": 0.50, "price": 120},
            {"name": "up", "probability": 0.25, "price": 170},
        ],
    }


def _candidate(scenario=None):
    return {
        "manual_rank": 1,
        "symbol": "MU",
        "theme": "memory_cycle",
        "decision_inputs": {
            "scenario": scenario,
            "evidence": {
                "quality": "medium",
                "as_of": "2026-07-16",
                "sources": ["filing", "market data"],
            },
            "next_catalyst": {
                "date": "2026-08-01",
                "label": "proof point",
                "source": "IR calendar",
            },
            "correlation_baskets": ["ai_capex", "hbm"],
            "instrument_lenses": ["stock", "deep_itm_leaps"],
            "threshold_origin": "approved_by_kevin",
        },
    }


def _thesis(status="active"):
    return {
        "symbol": "MU",
        "status": status,
        "invalidation": ["supply turns"],
        "next_review": "2026-08-01",
    }


def _watchlist():
    return {"total_score": 78, "coverage": 0.9, "action_band": "review"}


def _market():
    return {
        "symbol": "MU",
        "status": "healthy",
        "current_price": 100,
        "as_of": "2026-07-16",
        "source": "delayed public data",
    }


def test_valid_scenario_derives_expected_return_and_skew():
    scenario, errors = validate_scenario(_scenario())
    assert errors == []
    assert scenario["expected_price"] == 120
    assert scenario["expected_return_pct"] == 0.2
    assert scenario["downside_return_pct"] == -0.3
    assert scenario["upside_return_pct"] == 0.7


def test_invalid_probability_sum_rejects_whole_scenario():
    value = _scenario()
    value["cases"][0]["probability"] = 0.20
    scenario, errors = validate_scenario(value)
    assert scenario is None
    assert "scenario_probabilities_must_sum_to_one" in errors


def test_missing_scenario_never_becomes_decision_grade():
    row = assess_candidate(
        _candidate(None),
        thesis=_thesis(),
        watchlist=_watchlist(),
        options={"status": "ok"},
        market_context=_market(),
        regime="risk_on",
    )
    assert row["security_readiness"] == "not_decision_grade"
    assert row["decision_posture"] == "wait_for_proof"
    assert "scenario_missing" in row["missing_inputs"]
    assert row["not_a_trade_signal"] is True


def test_complete_inputs_are_review_ready_not_auto_buy():
    row = assess_candidate(
        _candidate(_scenario()),
        thesis=_thesis(),
        watchlist=_watchlist(),
        options={"status": "ok"},
        market_context=_market(),
        regime="risk_on",
    )
    assert row["security_readiness"] == "review_ready"
    assert row["decision_posture"] == "eligible_for_capital_review"
    assert row["not_a_trade_signal"] is True


def test_scenario_price_anchor_drift_invalidates_readiness():
    market = _market()
    market["current_price"] = 112
    row = assess_candidate(
        _candidate(_scenario()),
        thesis=_thesis(),
        watchlist=_watchlist(),
        options={"status": "ok"},
        market_context=market,
        regime="risk_on",
    )
    assert row["security_readiness"] == "not_decision_grade"
    assert "scenario_price_anchor_stale" in row["missing_inputs"]


def test_scenario_asof_drift_invalidates_readiness():
    market = _market()
    market["as_of"] = "2026-07-21"
    row = assess_candidate(
        _candidate(_scenario()),
        thesis=_thesis(),
        watchlist=_watchlist(),
        options={"status": "ok"},
        market_context=market,
        regime="risk_on",
    )
    assert row["security_readiness"] == "not_decision_grade"
    assert "scenario_market_asof_mismatch" in row["missing_inputs"]


def test_broken_company_thesis_suspends_security_ranking():
    row = assess_candidate(
        _candidate(_scenario()),
        thesis=_thesis("broken"),
        watchlist=_watchlist(),
        options={"status": "ok"},
        market_context=_market(),
        regime="risk_on",
    )
    assert row["security_readiness"] == "re_underwrite"
    assert row["decision_posture"] == "re_underwrite"


def test_decision_log_requires_enough_resolved_forecasts():
    log = [
        {"forecast_probability": 0.8, "outcome": True},
        {"forecast_probability": 0.6, "outcome": False},
    ]
    summary = summarize_decision_log(log)
    assert summary["brier_score"] == 0.2
    assert summary["status"] == "insufficient_history"
    assert summary["append_only"] is True


def test_payload_exposes_correlation_candidate_overlap():
    payload = build_decision_payload(
        allocation_doc={"candidates": [_candidate(None)]},
        thesis_doc={"symbols": [_thesis()]},
        watchlist_payload={
            "data": {
                "regime": "risk_on",
                "rows": [{"symbol": "MU", **_watchlist()}],
            }
        },
        options_payload={
            "data": {"rows": [{"symbol": "MU", "status": "ok"}]}
        },
        market_context_doc={"rows": [_market()]},
        decision_log=[],
    )
    assert payload["rows"][0]["symbol"] == "MU"
    baskets = {
        item["basket"] for item in payload["correlation_baskets"]
    }
    assert baskets == {"ai_capex", "hbm"}
