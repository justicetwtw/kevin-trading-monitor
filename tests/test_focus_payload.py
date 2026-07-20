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


def test_card_carries_as_of_and_flags_stale():
    from datetime import date

    trend = _trend_frame()
    # trend as_of comes from the last bar; with a far-future reference it is stale.
    card = build_focus_card(
        "NVDA", trend, thesis_state="watch",
        reference_date=date(2030, 1, 1),
    )
    assert card["as_of"] is not None
    assert "price_stale" in card["readiness_blockers"]


def test_card_missing_as_of_is_blocked():
    trend = _trend_frame()
    trend = {**trend, "as_of": None}
    card = build_focus_card("NVDA", trend, thesis_state="watch")
    assert "as_of_missing" in card["readiness_blockers"]


def test_focus_section_renders_when_enabled():
    # Actual dashboard render regression: enabled focus_engine must render the
    # Focus Engine section with rotation + securities + visible blockers.
    from src.dashboard.build_mission_control import _focus_section

    data = {
        "focus_engine": {
            "enabled": True,
            "mode": "shadow",
            "health": {"workflow_status": "partial", "error_codes": ["x"]},
            "data": {
                "market_regime": {"regime": "calm"},
                "portfolio_exceptions": {
                    "hedge_coverage_band": "has_protection_uncomputed",
                    "max_theme_concentration_band": "low",
                },
                "theme_rotation": {"rows": [{"theme": "ai_compute", "status": "ok",
                                             "rs_vs_qqq_20": 0.02, "rs_acceleration": 0.01,
                                             "breakout_20d_share": 0.5}]},
                "focus_securities": [{
                    "symbol": "NVDA", "company_thesis_state": "watch",
                    "timing_state": "trend_healthy", "exposure_posture": "core_hold",
                    "rs20_vs_qqq": 0.03, "valuation_status": "not_connected",
                    "options_capability_status": "screen_grade",
                    "readiness_blockers": ["valuation_not_connected"],
                    "as_of": "2026-07-18",
                }],
            },
        }
    }
    html = _focus_section(data)
    assert "Focus Engine (shadow)" in html
    assert "Theme rotation" in html
    assert "Focus securities" in html
    assert "ai_compute" in html
    assert "valuation_not_connected" in html


def test_focus_section_disabled_state():
    from src.dashboard.build_mission_control import _focus_section

    html = _focus_section({"focus_engine": {"enabled": False}})
    assert "disabled" in html.lower()
