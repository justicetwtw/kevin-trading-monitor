"""Privacy regression tests for persisted position-management state."""

import json

from cryptography.fernet import Fernet

from src.alerts import deduplication
from src.management import account_drawdown
from src.management.private_position_privacy import private_alert_dedup_key


def test_drawdown_file_encrypts_account_values(tmp_path, monkeypatch):
    store = tmp_path / "data_store"
    store.mkdir()
    monkeypatch.setattr("src.storage.state_manager.DATA_STORE_DIR", store)
    monkeypatch.setenv("POSITION_STATE_KEY", Fernet.generate_key().decode())

    account_drawdown.update_account_value(100_000)
    result = account_drawdown.update_account_value(78_000)

    path = store / "drawdown_history.json"
    public = json.loads(path.read_text(encoding="utf-8"))
    serialized = path.read_text(encoding="utf-8")

    assert result["alert_level"] == "level_2"
    assert abs(public["drawdown_pct"] - (-0.22)) < 0.001
    assert public["privacy"] == "fernet_encrypted_account_values"
    assert public["key_source"] == "actions_secret"
    assert "encrypted_state" in public
    assert "peak" not in public
    assert "current" not in public
    assert "100000" not in serialized
    assert "78000" not in serialized


def test_rotated_drawdown_key_fails_closed_and_resets(tmp_path, monkeypatch):
    store = tmp_path / "data_store"
    store.mkdir()
    monkeypatch.setattr("src.storage.state_manager.DATA_STORE_DIR", store)
    monkeypatch.setenv("POSITION_STATE_KEY", Fernet.generate_key().decode())
    account_drawdown.update_account_value(100_000)

    monkeypatch.setenv("POSITION_STATE_KEY", Fernet.generate_key().decode())
    result = account_drawdown.update_account_value(80_000)

    assert result["peak"] == 80_000
    assert result["current"] == 80_000
    assert result["drawdown_pct"] == 0.0


def test_private_alert_key_is_stable_and_opaque(monkeypatch):
    monkeypatch.setenv(
        "POSITIONS_JSON",
        json.dumps(
            {
                "stocks": [],
                "options": [
                    {
                        "id": "MU_PRIVATE_CALL",
                        "symbol": "MU",
                        "type": "long_call",
                        "strike": 220,
                        "expiry": "2027-01-15",
                        "contracts": 1,
                        "cost_per_contract": 17300,
                    }
                ],
            }
        ),
    )
    alert = {
        "option_id": "MU_PRIVATE_CALL",
        "symbol": "MU",
        "strike": 220,
        "level": "-30",
    }

    first = private_alert_dedup_key(alert, "leaps_pnl")
    second = private_alert_dedup_key(alert, "leaps_pnl")

    assert first == second
    assert first.startswith("private-position::leaps_pnl::")
    assert "MU" not in first
    assert "220" not in first
    assert deduplication._key({**alert, "dedup_key": first}) == first


def test_different_private_contracts_get_different_opaque_keys(monkeypatch):
    monkeypatch.setenv(
        "POSITIONS_JSON", json.dumps({"stocks": [], "options": []})
    )
    first = private_alert_dedup_key(
        {"option_id": "A", "symbol": "MU", "strike": 220},
        "leaps_pnl",
    )
    second = private_alert_dedup_key(
        {"option_id": "B", "symbol": "MU", "strike": 300},
        "leaps_pnl",
    )

    assert first != second
