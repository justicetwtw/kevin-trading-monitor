import pytest

from src.management import portfolio_decision_risk as risk
from src.runners import run_position_check


def _thesis_doc():
    return {
        "themes": [
            {
                "id": "ai_capex",
                "subthemes": [
                    {"id": "compute", "symbols": ["NVDA"]},
                    {"id": "memory_interconnect", "symbols": ["MU"]},
                ],
            },
            {
                "id": "memory_cycle",
                "subthemes": [
                    {"id": "hbm", "symbols": ["MU", "NVDA"]},
                    {"id": "nand", "symbols": ["MU", "SNDK"]},
                ],
            },
            {
                "id": "portfolio_hedge",
                "subthemes": [
                    {
                        "id": "broad_market_hedge",
                        "symbols": ["QQQ", "SPY", "SMH"],
                    }
                ],
            },
        ],
        "symbols": [
            {"symbol": "MU", "theme": "memory_cycle"},
            {"symbol": "NVDA", "theme": "ai_capex"},
        ],
    }


def _snapshot(with_thesis=True):
    return {
        "mode": "mode_1",
        "position_source": "actions_secret",
        "stocks": [
            {
                "symbol": "NVDA",
                "shares": 100,
                **({"thesis_id": "ai_capex"} if with_thesis else {}),
            }
        ],
        "options": [
            {
                "symbol": "MU",
                "type": "long_call",
                "strike": 100,
                "expiry": "2027-01-15",
                "contracts": 1,
                **({"thesis_id": "memory_cycle"} if with_thesis else {}),
            },
            {
                "symbol": "QQQ",
                "type": "long_put",
                "strike": 400,
                "expiry": "2026-09-18",
                "contracts": 1,
                **({"thesis_id": "portfolio_hedge"} if with_thesis else {}),
            },
        ],
        "total_estimated_value": 100000,
        "valuation_complete": True,
        "valuation_missing_count": 0,
        "n_long_options": 2,
        "n_short_options": 0,
        "snapshot_at": "2026-07-16T00:00:00+00:00",
    }


def _summary():
    return {
        "gross_delta_notional": 140000,
        "rows": [
            {
                "kind": "stock",
                "symbol": "NVDA",
                "theme": "ai_capex",
                "delta_notional": 100000,
                "market_data_ok": True,
            },
            {
                "kind": "long_call",
                "symbol": "MU",
                "theme": "memory_cycle",
                "delta_notional": 30000,
                "dte": 183,
                "market_data_ok": True,
            },
            {
                "kind": "long_put",
                "symbol": "QQQ",
                "theme": "portfolio_hedge",
                "delta_notional": -10000,
                "dte": 64,
                "market_data_ok": True,
            },
        ],
    }


def test_private_decision_risk_maps_overlapping_baskets_and_rolls(monkeypatch):
    monkeypatch.setattr(risk, "read_json", lambda *args, **kwargs: _thesis_doc())
    result = risk.analyze_portfolio_decision_risk(_summary(), _snapshot())
    baskets = {item["basket"]: item for item in result["basket_exposure"]}
    assert "ai_capex" in baskets
    assert "memory_cycle" in baskets
    assert "hbm" in baskets
    assert "nand" in baskets
    assert "portfolio_hedge" in baskets
    assert result["missing_thesis_id_count"] == 0
    assert result["invalid_thesis_id_count"] == 0
    assert result["hedge_coverage_ratio"] == pytest.approx(10000 / 130000)
    assert result["roll_window_counts"] == {
        "dte_le_90": 1,
        "dte_le_180": 1,
        "dte_le_270": 2,
    }
    assert "option_roll_window_le_90d" in result["review_flags"]


def test_unknown_thesis_id_is_explicitly_invalid(monkeypatch):
    monkeypatch.setattr(risk, "read_json", lambda *args, **kwargs: _thesis_doc())
    snapshot = _snapshot()
    snapshot["stocks"][0]["thesis_id"] = "invented_thesis"
    result = risk.analyze_portfolio_decision_risk(_summary(), snapshot)
    assert result["invalid_thesis_id_count"] == 1
    assert "position_thesis_id_invalid" in result["review_flags"]


def test_public_state_cannot_reveal_symbols_or_basket_names(monkeypatch):
    monkeypatch.setattr(risk, "read_json", lambda *args, **kwargs: _thesis_doc())
    private = risk.analyze_portfolio_decision_risk(_summary(), _snapshot())
    public = risk.public_decision_risk_state(private)
    serialized = str(public)
    for private_value in (
        "MU",
        "NVDA",
        "QQQ",
        "ai_capex",
        "memory_cycle",
        "portfolio_hedge",
    ):
        assert private_value not in serialized
    assert public["invalid_thesis_id_count"] == 0
    assert public["privacy"] == "aggregate_decision_risk_only"


def test_missing_thesis_id_is_a_safe_degraded_workflow_code(monkeypatch):
    monkeypatch.setattr(run_position_check, "scan_all_leaps", lambda: [])
    monkeypatch.setattr(run_position_check, "scan_all_shorts", lambda: [])
    monkeypatch.setattr(run_position_check, "scan_all_hedges", lambda: [])
    monkeypatch.setattr(
        run_position_check, "get_account_snapshot", lambda: _snapshot(False)
    )
    monkeypatch.setattr(
        run_position_check,
        "update_account_value",
        lambda value: {"alert_level": "normal"},
    )
    monkeypatch.setattr(
        run_position_check,
        "_analyze_and_send_private_risk",
        lambda snapshot: (
            True,
            {
                "missing_thesis_id_count": 3,
                "invalid_thesis_id_count": 0,
                "unmapped_symbol_count": 0,
                "roll_window_counts": {},
                "review_flags": ["position_thesis_id_missing"],
            },
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
    assert "position_thesis_id_missing" in public["error_codes"]
    assert public["decision_risk"]["missing_thesis_id_count"] == 3
    serialized = str(public["decision_risk"])
    for private_value in (
        "MU",
        "NVDA",
        "QQQ",
        "ai_capex",
        "memory_cycle",
        "portfolio_hedge",
    ):
        assert private_value not in serialized


def test_invalid_thesis_id_is_a_safe_degraded_workflow_code(monkeypatch):
    monkeypatch.setattr(run_position_check, "scan_all_leaps", lambda: [])
    monkeypatch.setattr(run_position_check, "scan_all_shorts", lambda: [])
    monkeypatch.setattr(run_position_check, "scan_all_hedges", lambda: [])
    monkeypatch.setattr(
        run_position_check, "get_account_snapshot", lambda: _snapshot(True)
    )
    monkeypatch.setattr(
        run_position_check,
        "update_account_value",
        lambda value: {"alert_level": "normal"},
    )
    monkeypatch.setattr(
        run_position_check,
        "_analyze_and_send_private_risk",
        lambda snapshot: (
            True,
            {
                "missing_thesis_id_count": 0,
                "invalid_thesis_id_count": 1,
                "unmapped_symbol_count": 0,
                "roll_window_counts": {},
                "review_flags": ["position_thesis_id_invalid"],
            },
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
    assert "position_thesis_id_invalid" in public["error_codes"]
    assert public["decision_risk"]["invalid_thesis_id_count"] == 1
