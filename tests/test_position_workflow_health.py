"""Redacted workflow health and public dashboard privacy tests."""

from src.dashboard.build_mission_control import build_payloads
from src.runners import run_position_check
from src.storage import mission_control_store


def test_mode1_missing_private_positions_fails_with_safe_error_code(monkeypatch):
    monkeypatch.setattr(run_position_check, "scan_all_leaps", lambda: [])
    monkeypatch.setattr(run_position_check, "scan_all_shorts", lambda: [])
    monkeypatch.setattr(run_position_check, "scan_all_hedges", lambda: [])
    monkeypatch.setattr(
        run_position_check,
        "get_account_snapshot",
        lambda: {
            "mode": "mode_1",
            "position_source": "actions_secret",
            "stocks": [],
            "options": [],
            "total_estimated_value": 0.0,
            "n_long_options": 0,
            "n_short_options": 0,
            "snapshot_at": "2026-07-16T00:00:00+00:00",
        },
    )
    writes = {}
    monkeypatch.setattr(
        run_position_check,
        "write_json",
        lambda filename, value: writes.setdefault(filename, value) is value,
    )

    assert run_position_check.main() == 1
    public = writes["position_snapshot.json"]
    assert public["workflow_status"] == "degraded"
    assert public["error_codes"] == ["private_positions_missing_or_invalid"]
    assert public["decision_risk"]["privacy"] == "aggregate_decision_risk_only"
    assert "stocks" not in public
    assert "options" not in public


def test_public_dashboard_forces_legacy_leaps_redaction():
    payloads = build_payloads()
    data = payloads["leaps_exposure"]["data"]
    assert data["positions"] == []
    assert data["status"] == "redacted_private_positions"
    serialized = str(data)
    for private_field in (
        "strike",
        "expiry",
        "cost_per_contract",
        "current_price_per_contract",
        "pnl_pct",
    ):
        assert private_field not in serialized


def test_mission_control_surfaces_safe_position_error_codes(monkeypatch):
    def fake_read_json(filename, default=None):
        values = {
            "position_snapshot.json": {
                "mode": "mode_1",
                "position_source": "actions_secret",
                "configured": True,
                "position_count": 2,
                "n_long_options": 1,
                "n_short_options": 0,
                "snapshot_at": "2026-07-16T00:00:00+00:00",
                "workflow_status": "degraded",
                "error_codes": ["private_brief_failed"],
                "decision_risk": {
                    "missing_thesis_id_count": 0,
                    "privacy": "aggregate_decision_risk_only",
                },
                "privacy": "redacted_public_state",
            },
            "drawdown_history.json": {
                "drawdown_pct": -0.1,
                "alert_level": "level_1",
                "key_source": "actions_secret",
            },
            "thesis_tracker.json": {"themes": [], "symbols": []},
            "capital_allocation.json": {"candidates": []},
        }
        return values.get(filename, default)

    monkeypatch.setattr(mission_control_store, "read_json", fake_read_json)
    monkeypatch.setattr(
        mission_control_store.dashboard_store,
        "build_regime_payload",
        lambda: {"data": {"regime": "neutral", "modifier": 1.0}},
    )
    monkeypatch.setattr(
        mission_control_store.dashboard_store,
        "build_watchlist_scores",
        lambda: {"data": {"rows": []}},
    )
    monkeypatch.setattr(
        mission_control_store.dashboard_store,
        "build_options_flow",
        lambda: {"data": {"rows": []}},
    )

    payload = mission_control_store.build_mission_control_payload()

    account = payload["data"]["account"]
    assert account["workflow_status"] == "degraded"
    assert account["error_codes"] == ["private_brief_failed"]
    attention = payload["data"]["attention"]
    assert any(
        item["title"] == "Private position workflow is degraded"
        and "private_brief_failed" in item["detail"]
        for item in attention
    )


def test_mission_control_flags_plaintext_account_values(monkeypatch):
    def fake_read_json(filename, default=None):
        values = {
            "position_snapshot.json": {},
            "drawdown_history.json": {
                "peak": 100000,
                "current": 90000,
                "drawdown_pct": -0.1,
            },
            "thesis_tracker.json": {"themes": [], "symbols": []},
            "capital_allocation.json": {"candidates": []},
        }
        return values.get(filename, default)

    monkeypatch.setattr(mission_control_store, "read_json", fake_read_json)
    monkeypatch.setattr(
        mission_control_store.dashboard_store,
        "build_regime_payload",
        lambda: {"data": {}},
    )
    monkeypatch.setattr(
        mission_control_store.dashboard_store,
        "build_watchlist_scores",
        lambda: {"data": {"rows": []}},
    )
    monkeypatch.setattr(
        mission_control_store.dashboard_store,
        "build_options_flow",
        lambda: {"data": {"rows": []}},
    )

    payload = mission_control_store.build_mission_control_payload()
    assert any(
        item["severity"] == "P0" and item["category"] == "privacy"
        for item in payload["data"]["attention"]
    )
