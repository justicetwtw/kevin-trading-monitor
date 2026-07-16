"""Trading Monitor v2 Mission Control tests."""

import json

from src.dashboard.build_mission_control import build_all
from src.runners import run_position_check
from src.storage.mission_control_store import build_mission_control_payload


def test_mission_control_payload_has_first_screen_contract():
    payload = build_mission_control_payload()
    assert payload["schema_version"] == 1
    data = payload["data"]
    assert set(data) >= {
        "summary",
        "attention",
        "account",
        "themes",
        "theses",
        "allocation_queue",
        "disclaimer",
    }
    assert data["summary"]["needs_attention_count"] == len(data["attention"])
    assert data["summary"]["estimated_account_value"] is None
    assert data["account"]["positions"] == []
    assert all(
        row["not_a_trade_signal"] is True
        for row in data["allocation_queue"]
    )


def test_memory_thesis_separates_hbm_dram_and_nand():
    payload = build_mission_control_payload()
    memory = next(
        theme
        for theme in payload["data"]["themes"]
        if theme["id"] == "memory_cycle"
    )
    subthemes = {sub["id"] for sub in memory["subthemes"]}
    assert {"hbm", "commodity_dram", "nand"} <= subthemes


def test_mission_control_build_smoke(tmp_path):
    output = tmp_path / "dashboard"
    payloads = build_all(output)
    assert "mission_control" in payloads
    html = (output / "index.html").read_text(encoding="utf-8")
    for text in (
        "Kevin Trading Mission Control",
        "Needs attention",
        "Theme map",
        "Capital allocation queue",
        "Portfolio workflow health",
        "Symbol thesis tracker",
    ):
        assert text in html
    mission_json = json.loads(
        (output / "data" / "mission_control.json").read_text(
            encoding="utf-8"
        )
    )
    assert mission_json["data"]["summary"]


def test_position_runner_persists_redacted_snapshot_and_uses_correct_total(
    monkeypatch,
):
    monkeypatch.setattr(run_position_check, "scan_all_leaps", lambda: [])
    monkeypatch.setattr(run_position_check, "scan_all_shorts", lambda: [])
    monkeypatch.setattr(run_position_check, "scan_all_hedges", lambda: [])
    monkeypatch.setattr(
        run_position_check, "route_alert", lambda alert: False
    )
    monkeypatch.setattr(
        run_position_check,
        "_send_private_risk_brief",
        lambda snapshot: True,
    )

    snapshot = {
        "mode": "mode_1",
        "position_source": "actions_secret",
        "stocks": [{"symbol": "PRIVATE", "shares": 10}],
        "options": [
            {
                "symbol": "PRIVATE",
                "type": "long_call",
                "strike": 1,
                "expiry": "2027-01-15",
            }
        ],
        "total_estimated_value": 123456.0,
        "n_long_options": 1,
        "n_short_options": 0,
        "snapshot_at": "2026-07-16T00:00:00+00:00",
    }
    monkeypatch.setattr(
        run_position_check, "get_account_snapshot", lambda: snapshot
    )

    writes = {}

    def _capture(filename, value):
        writes[filename] = value
        return True

    monkeypatch.setattr(run_position_check, "write_json", _capture)
    totals = []
    monkeypatch.setattr(
        run_position_check,
        "update_account_value",
        lambda total: totals.append(total) or {"alert_level": "normal"},
    )

    assert run_position_check.main() == 0

    public = writes["position_snapshot.json"]
    assert public["configured"] is True
    assert public["position_count"] == 2
    assert public["n_long_options"] == 1
    assert public["workflow_status"] == "healthy"
    assert public["error_codes"] == []
    assert public["privacy"] == "redacted_public_state"
    assert "stocks" not in public
    assert "options" not in public
    assert "total_estimated_value" not in public
    assert totals == [123456.0]
