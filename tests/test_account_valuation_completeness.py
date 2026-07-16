"""Account drawdown must never use a partial portfolio valuation."""

import json

from src.management import current_positions
from src.runners import run_position_check


def _positions():
    return {
        "stocks": [{"symbol": "AAA", "shares": 10}],
        "options": [
            {
                "symbol": "AAA",
                "type": "long_call",
                "strike": 10,
                "expiry": "2027-12-17",
                "contracts": 1,
                "cost_per_contract": 500,
            }
        ],
    }


def test_snapshot_fails_closed_when_one_position_cannot_be_valued(monkeypatch):
    monkeypatch.setenv("POSITIONS_JSON", json.dumps(_positions()))
    monkeypatch.setattr(current_positions, "POSITION_MODE", "mode_1")
    monkeypatch.setattr(
        current_positions, "_estimate_stock_value", lambda stock: 1000.0
    )
    monkeypatch.setattr(
        current_positions, "_estimate_option_value", lambda option: None
    )

    snapshot = current_positions.get_account_snapshot()

    assert snapshot["valuation_complete"] is False
    assert snapshot["valuation_missing_count"] == 1
    assert snapshot["total_estimated_value"] is None


def test_snapshot_returns_total_only_when_every_position_is_valued(monkeypatch):
    monkeypatch.setenv("POSITIONS_JSON", json.dumps(_positions()))
    monkeypatch.setattr(current_positions, "POSITION_MODE", "mode_1")
    monkeypatch.setattr(
        current_positions, "_estimate_stock_value", lambda stock: 1000.0
    )
    monkeypatch.setattr(
        current_positions, "_estimate_option_value", lambda option: 500.0
    )

    snapshot = current_positions.get_account_snapshot()

    assert snapshot["valuation_complete"] is True
    assert snapshot["valuation_missing_count"] == 0
    assert snapshot["total_estimated_value"] == 1500.0


def test_runner_does_not_update_drawdown_from_partial_valuation(monkeypatch):
    monkeypatch.setattr(run_position_check, "scan_all_leaps", lambda: [])
    monkeypatch.setattr(run_position_check, "scan_all_shorts", lambda: [])
    monkeypatch.setattr(run_position_check, "scan_all_hedges", lambda: [])
    monkeypatch.setattr(
        run_position_check,
        "get_account_snapshot",
        lambda: {
            "mode": "mode_1",
            "position_source": "actions_secret",
            "stocks": [{"symbol": "PRIVATE", "shares": 1}],
            "options": [],
            "total_estimated_value": None,
            "valuation_complete": False,
            "valuation_missing_count": 1,
            "n_long_options": 0,
            "n_short_options": 0,
            "snapshot_at": "2026-07-16T00:00:00+00:00",
        },
    )
    monkeypatch.setattr(
        run_position_check, "_send_private_risk_brief", lambda snapshot: True
    )
    monkeypatch.setattr(
        run_position_check,
        "update_account_value",
        lambda total: (_ for _ in ()).throw(
            AssertionError("drawdown must not use partial valuation")
        ),
    )
    writes = {}
    monkeypatch.setattr(
        run_position_check,
        "write_json",
        lambda filename, value: writes.setdefault(filename, value) is value,
    )

    assert run_position_check.main() == 1
    public = writes["position_snapshot.json"]
    assert public["valuation_complete"] is False
    assert public["valuation_missing_count"] == 1
    assert "account_value_unavailable" in public["error_codes"]
