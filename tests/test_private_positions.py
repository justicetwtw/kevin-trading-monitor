"""Private runtime position input and public redaction tests."""

import json

from src.management import current_positions
from src.runners import run_position_check


def _secret_payload() -> dict:
    return {
        "stocks": [
            {
                "symbol": "PRIVATE_STOCK",
                "shares": 12,
                "avg_cost": 101.5,
                "thesis_id": "private_thesis",
            }
        ],
        "options": [
            {
                "id": "PRIVATE_OPTION",
                "symbol": "PRIVATE_STOCK",
                "type": "long_call",
                "strike": 100,
                "expiry": "2027-01-15",
                "contracts": 2,
                "cost_per_contract": 2500,
                "thesis_id": "private_thesis",
            }
        ],
    }


def test_actions_secret_takes_priority_over_public_file(monkeypatch):
    expected = _secret_payload()
    monkeypatch.setenv("POSITIONS_JSON", json.dumps(expected))
    monkeypatch.setattr(
        current_positions,
        "read_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("public file must not be read when secret exists")
        ),
    )

    assert current_positions.load_positions() == expected
    assert current_positions.get_position_source() == "actions_secret"


def test_invalid_secret_fails_closed_without_file_fallback(monkeypatch):
    monkeypatch.setenv("POSITIONS_JSON", "{not-valid-json")
    monkeypatch.setattr(
        current_positions,
        "read_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("malformed secret must not fall back to public file")
        ),
    )

    assert current_positions.load_positions() == {"stocks": [], "options": []}


def test_invalid_secret_schema_fails_closed(monkeypatch):
    payload = _secret_payload()
    payload["options"][0]["type"] = "unsupported"
    monkeypatch.setenv("POSITIONS_JSON", json.dumps(payload))

    assert current_positions.load_positions() == {"stocks": [], "options": []}


def test_account_snapshot_uses_secret_but_marks_source_only(monkeypatch):
    monkeypatch.setenv("POSITIONS_JSON", json.dumps(_secret_payload()))
    monkeypatch.setattr(current_positions, "POSITION_MODE", "mode_1")
    monkeypatch.setattr(current_positions, "_estimate_stock_value", lambda stock: 1200.0)
    monkeypatch.setattr(current_positions, "_estimate_option_value", lambda option: 7000.0)

    snapshot = current_positions.get_account_snapshot()

    assert snapshot["position_source"] == "actions_secret"
    assert snapshot["total_estimated_value"] == 8200.0
    assert snapshot["stocks"][0]["symbol"] == "PRIVATE_STOCK"


def test_public_snapshot_never_contains_private_details():
    private = {
        "mode": "mode_1",
        "position_source": "actions_secret",
        "stocks": [{"symbol": "PRIVATE_STOCK", "shares": 12}],
        "options": [
            {
                "symbol": "PRIVATE_STOCK",
                "strike": 100,
                "expiry": "2027-01-15",
                "cost_per_contract": 2500,
            }
        ],
        "total_estimated_value": 999999.0,
        "n_long_options": 1,
        "n_short_options": 0,
        "snapshot_at": "2026-07-16T00:00:00+00:00",
    }

    public = run_position_check._public_snapshot(private)

    assert public["configured"] is True
    assert public["position_count"] == 2
    assert public["privacy"] == "redacted_public_state"
    assert "stocks" not in public
    assert "options" not in public
    assert "total_estimated_value" not in public
    serialized = json.dumps(public)
    assert "PRIVATE_STOCK" not in serialized
    assert "999999" not in serialized
