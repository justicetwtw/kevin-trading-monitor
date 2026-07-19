"""Focus payload / feature-flag / dashboard tests(驗收 #8)。"""

import numpy as np
import pandas as pd

from src.focus.payload import build_focus_card, build_focus_payload
from src.focus.trend import compute_trend_frame


def _trend_frame():
    closes = list(np.linspace(80, 120, 260))
    idx = pd.date_range("2024-01-01", periods=260, freq="B")
    frame = pd.DataFrame(
        {"Close": closes, "High": [c * 1.01 for c in closes],
         "Low": [c * 0.99 for c in closes], "Volume": [1_000_000] * 260},
        index=idx,
    )
    bench = frame.copy()
    return compute_trend_frame(frame, benchmark_frames={"QQQ": bench, "SMH": bench})


def test_feature_flag_off_returns_disabled_envelope(monkeypatch):
    monkeypatch.delenv("FOCUS_ENGINE_ENABLED", raising=False)
    payload = build_focus_payload(cards=[{"symbol": "NVDA"}])
    assert payload["enabled"] is False
    assert payload["data"] is None


def test_feature_flag_on_builds_data(monkeypatch):
    monkeypatch.setenv("FOCUS_ENGINE_ENABLED", "1")
    payload = build_focus_payload(cards=[{"symbol": "NVDA", "readiness_blockers": []}])
    assert payload["enabled"] is True
    assert payload["mode"] in ("shadow", "display_only")
    assert payload["data"]["counts"]["focus_card_count"] == 1
    assert "does not override" in payload["rollout_note"].lower()


def test_focus_card_exposes_state_triplet_and_blockers():
    trend = _trend_frame()
    card = build_focus_card(
        "NVDL", trend, thesis_state="watch",
        options_capability={"status": "screen_grade"},
        valuation_status="not_connected",
    )
    # 三狀態俱在
    assert card["company_thesis_state"] == "watch"
    assert card["timing_state"] in {
        "trend_healthy", "pullback_test", "breakout_confirmed",
        "overheated", "bottom_watch", "trend_damaged", "reclaim_confirmed",
    }
    assert card["exposure_posture"]
    # NVDL 是 2x → underlying 收斂到 NVDA
    assert card["symbol"] == "NVDA"
    assert card["leverage"] == 2.0
    # 缺 valuation → blocker 可見
    assert "valuation_not_connected" in card["readiness_blockers"]
    assert card["not_a_trade_signal"] is True
    assert card["source"]


def test_focus_card_unavailable_trend_shows_blocker():
    card = build_focus_card("NVDA", {"status": "insufficient_data"}, thesis_state="watch")
    assert card["timing_state"] == "insufficient_data"
    assert "price_trend_unavailable" in card["readiness_blockers"]


def test_mission_control_includes_focus_engine_block(monkeypatch):
    monkeypatch.delenv("FOCUS_ENGINE_ENABLED", raising=False)
    from src.storage.mission_control_store import build_mission_control_payload

    payload = build_mission_control_payload()
    assert "focus_engine" in payload["data"]
    # default (flag off, no shadow state) → disabled envelope, dashboard stays honest
    assert payload["data"]["focus_engine"]["enabled"] is False
