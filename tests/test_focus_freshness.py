"""Freshness + stale-data gating tests (round 2)."""

from datetime import date

import numpy as np
import pandas as pd

from src.focus.freshness import (
    frame_as_of,
    freshness,
    is_frame_fresh,
    parse_as_of,
)
from src.focus.payload import build_focus_card
from src.focus.state_machine import classify_timing, evaluate_symbol


def test_freshness_fresh_stale_missing():
    ref = date(2026, 7, 20)
    assert freshness("2026-07-19", ref)["status"] == "fresh"
    assert freshness("2026-07-01", ref)["status"] == "stale"
    assert freshness(None, ref)["status"] == "missing"
    assert freshness("2026-07-19", None)["status"] == "unknown_age"


def test_frame_as_of_and_is_fresh():
    idx = pd.date_range("2026-07-10", periods=60, freq="B")
    frame = pd.DataFrame({"Close": np.linspace(10, 20, 60)}, index=idx)
    as_of = frame_as_of(frame)
    assert parse_as_of(as_of) is not None
    # far-future reference makes the frame stale
    assert is_frame_fresh(frame, date(2030, 1, 1)) is False


def _ok_trend():
    # A healthy, add-eligible trend fixture (RS leading, rising 50DMA).
    def rs(v):
        return {w: {"value": v, "status": "ok"} for w in (20, 63, 126)}

    return {
        "status": "ok",
        "as_of": "2026-07-18",
        "close": 102.0,
        "sma": {20: 101.0, 50: 98.0, 200: 90.0},
        "sma_slope": {20: 0.02, 50: 0.02, 200: 0.0},
        "above_sma": {20: True, 50: True, 200: True},
        "rsi": 55.0,
        "bollinger": {"pct_b": 0.5, "touch_lower": False, "touch_upper": False},
        "donchian": {20: {"status": "inside"}, 55: {"status": "inside"}},
        "reclaim": {"reclaimed": False, "status": "ok"},
        "volume_percentile": 0.6,
        "rs_vs_qqq": rs(0.05),
        "rs_vs_smh": rs(0.05),
        "rs_vs_theme": rs(0.05),
    }


def test_stale_benchmark_blocks_add_ready():
    trend = _ok_trend()
    stale_bench = {"status": "stale", "as_of": "2026-06-01", "age_days": 49}
    card = build_focus_card(
        "NVDA", trend, thesis_state="intact",
        benchmark_freshness=stale_bench, reference_date=date(2026, 7, 20),
    )
    assert "rs_benchmark_stale" in card["readiness_blockers"]
    assert card["add_allowed"] is False
    assert card["long_entry_eligible"] is False


def test_stale_price_blocks_add_ready():
    trend = _ok_trend()
    card = build_focus_card(
        "NVDA", trend, thesis_state="intact",
        reference_date=date(2030, 1, 1),  # makes the 2026 as_of stale
    )
    assert "price_stale" in card["readiness_blockers"]
    assert card["add_allowed"] is False


def test_fresh_price_but_missing_valuation_and_options_is_not_add_ready():
    # Fresh price/benchmark alone is NOT permission to add: missing valuation
    # approval and unavailable options confirmation must block add-ready.
    trend = _ok_trend()
    fresh_bench = {"status": "fresh", "as_of": "2026-07-18", "age_days": 2}
    card = build_focus_card(
        "NVDA", trend, thesis_state="intact",
        benchmark_freshness=fresh_bench, reference_date=date(2026, 7, 20),
    )
    assert "rs_benchmark_stale" not in card["readiness_blockers"]
    assert "price_stale" not in card["readiness_blockers"]
    assert "valuation_not_approved" in card["readiness_blockers"]
    assert "options_confirmation_unavailable" in card["readiness_blockers"]
    assert card["add_allowed"] is False


def _approved_valuation_evidence():
    # Decision-grade valuation evidence: source + fresh as_of + coverage + value band.
    return {
        "approval_status": "approved",
        "source": "kevin_manual_review",
        "as_of": "2026-07-10",
        "coverage": 0.8,
        "value_band": {"bear": 90.0, "base": 130.0, "bull": 170.0},
    }


def test_approved_valuation_and_confirmed_options_allow_add():
    trend = _ok_trend()
    fresh_bench = {"status": "fresh", "as_of": "2026-07-18", "age_days": 2}
    confirmed = {
        "status": "confirmed_ok",
        "downside_pressure_worsening": False,
        "downside_pressure_confirmed_ok": True,
    }
    card = build_focus_card(
        "NVDA", trend, thesis_state="intact",
        valuation_status="approved",
        valuation_evidence=_approved_valuation_evidence(),
        options_pressure=confirmed,
        benchmark_freshness=fresh_bench, reference_date=date(2026, 7, 20),
    )
    assert "valuation_not_approved" not in card["readiness_blockers"]
    assert "options_confirmation_unavailable" not in card["readiness_blockers"]
    assert card["valuation_decision_grade"] is True
    assert card["add_allowed"] is True


def test_bare_approved_string_without_evidence_cannot_add():
    # finding P1: a bare valuation status string is NOT decision-grade approval.
    trend = _ok_trend()
    fresh_bench = {"status": "fresh", "as_of": "2026-07-18", "age_days": 2}
    confirmed = {"status": "confirmed_ok", "downside_pressure_worsening": False,
                 "downside_pressure_confirmed_ok": True}
    card = build_focus_card(
        "NVDA", trend, thesis_state="intact",
        valuation_status="approved",       # bare string, no evidence object
        options_pressure=confirmed,
        benchmark_freshness=fresh_bench, reference_date=date(2026, 7, 20),
    )
    assert card["valuation_decision_grade"] is False
    assert "valuation_not_approved" in card["readiness_blockers"]
    assert card["add_allowed"] is False


def test_stale_valuation_evidence_cannot_add():
    # Approved status but the supporting evidence as_of is far stale → blocked.
    trend = _ok_trend()
    fresh_bench = {"status": "fresh", "as_of": "2026-07-18", "age_days": 2}
    confirmed = {"status": "confirmed_ok", "downside_pressure_worsening": False,
                 "downside_pressure_confirmed_ok": True}
    stale_evidence = {
        "approval_status": "approved", "source": "kevin_manual_review",
        "as_of": "2026-01-01", "coverage": 0.8,   # >45d before 2026-07-20
        "value_band": {"bear": 90.0, "base": 130.0, "bull": 170.0},
    }
    card = build_focus_card(
        "NVDA", trend, thesis_state="intact",
        valuation_status="approved", valuation_evidence=stale_evidence,
        options_pressure=confirmed,
        benchmark_freshness=fresh_bench, reference_date=date(2026, 7, 20),
    )
    assert card["valuation_decision_grade"] is False
    assert "valuation_not_approved" in card["readiness_blockers"]
    assert card["add_allowed"] is False


def test_options_unavailable_keeps_wait_for_proof():
    from src.focus.providers import build_options_pressure

    trend = _ok_trend()
    fresh_bench = {"status": "fresh", "as_of": "2026-07-18", "age_days": 2}
    # screen-grade snapshot: no skew/gamma/OI → pressure status unavailable
    pressure = build_options_pressure({"current_atm_iv": 0.4, "put_call_volume_ratio": 0.9})
    assert pressure["status"] == "unavailable"
    card = build_focus_card(
        "NVDA", trend, thesis_state="intact",
        valuation_status="approved",  # valuation ok, but options unavailable
        options_pressure=pressure,
        benchmark_freshness=fresh_bench, reference_date=date(2026, 7, 20),
    )
    assert card["add_allowed"] is False
    assert card["exposure_posture"] == "wait_for_proof"


def test_evaluate_symbol_data_blocked_downgrades():
    trend = _ok_trend()
    normal = evaluate_symbol(trend, "intact", data_blocked=False)
    blocked = evaluate_symbol(trend, "intact", data_blocked=True)
    assert normal["add_allowed"] is True
    assert blocked["add_allowed"] is False
    assert blocked["long_entry_eligible"] is False
    assert "data_blocked_stale_or_partial" in blocked["exposure_reasons"]


def test_options_pressure_worsening_blocks_add():
    trend = _ok_trend()
    clean = classify_timing(trend, {"downside_pressure_worsening": False})
    worsening = classify_timing(trend, {"downside_pressure_worsening": True})
    assert clean["long_entry_eligible"] is True
    assert worsening["long_entry_eligible"] is False
    assert "options_pressure_worsening" in worsening["flags"]


def test_stress_regime_exposure_cap_blocks_add():
    # Even fresh + approved-valuation + confirmed-options cannot add if the
    # market regime caps new exposure (stress / unknown regime).
    trend = _ok_trend()
    fresh_bench = {"status": "fresh", "as_of": "2026-07-18", "age_days": 2}
    confirmed = {"status": "confirmed_ok", "downside_pressure_worsening": False,
                 "downside_pressure_confirmed_ok": True}
    cap = {"max_exposure_multiplier": 0.0, "blocks_new_exposure": True, "regime": "stress"}
    card = build_focus_card(
        "NVDA", trend, thesis_state="intact",
        valuation_status="approved", valuation_evidence=_approved_valuation_evidence(),
        options_pressure=confirmed,
        benchmark_freshness=fresh_bench, reference_date=date(2026, 7, 20),
        market_exposure_cap=cap,
    )
    assert "market_regime_caps_exposure" in card["readiness_blockers"]
    assert card["add_allowed"] is False
    assert card["proposed_size_multiplier"] == 0.0


def test_elevated_regime_materially_reduces_proposed_size():
    # An elevated regime (cap 0.5) does not block add, but must materially reduce
    # the proposed size (0.5, not full 1.0) — the cap is enforced, not display-only.
    trend = _ok_trend()
    fresh_bench = {"status": "fresh", "as_of": "2026-07-18", "age_days": 2}
    confirmed = {"status": "confirmed_ok", "downside_pressure_worsening": False,
                 "downside_pressure_confirmed_ok": True}
    elevated = {"max_exposure_multiplier": 0.5, "blocks_new_exposure": False,
                "reduces_new_exposure": True, "regime": "elevated"}
    card = build_focus_card(
        "NVDA", trend, thesis_state="intact",
        valuation_status="approved", valuation_evidence=_approved_valuation_evidence(),
        options_pressure=confirmed,
        benchmark_freshness=fresh_bench, reference_date=date(2026, 7, 20),
        market_exposure_cap=elevated,
    )
    assert card["add_allowed"] is True
    assert card["proposed_size_multiplier"] == 0.5  # materially reduced vs 1.0


def test_elevated_regime_reduces_leveraged_gross_further():
    # For a leveraged instrument the non-zero cap applies to gross exposure, so a
    # 2x name under a 0.5 cap is reduced below the cap (0.25), not left at 0.5/1.0.
    trend = _ok_trend()
    fresh_bench = {"status": "fresh", "as_of": "2026-07-18", "age_days": 2}
    confirmed = {"status": "confirmed_ok", "downside_pressure_worsening": False,
                 "downside_pressure_confirmed_ok": True}
    elevated = {"max_exposure_multiplier": 0.5, "blocks_new_exposure": False,
                "reduces_new_exposure": True, "regime": "elevated"}
    card = build_focus_card(
        "NVDL", trend, thesis_state="intact",  # NVDL = 2x NVDA
        valuation_status="approved", valuation_evidence=_approved_valuation_evidence(),
        options_pressure=confirmed,
        benchmark_freshness=fresh_bench, reference_date=date(2026, 7, 20),
        market_exposure_cap=elevated,
    )
    assert card["proposed_size_multiplier"] == 0.25  # 0.5 / 2x leverage
