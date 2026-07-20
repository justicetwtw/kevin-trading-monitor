"""Provider capability contract tests(驗收 #6)。"""

from src.focus.providers import (
    NullEstimatesProvider,
    OPTIONS_CAPABILITY_FIELDS,
    PublicVolatilityIndexProvider,
    YFinanceFocusOptionsProvider,
)


def test_options_unsupported_fields_are_none():
    provider = YFinanceFocusOptionsProvider()
    snap = provider.get_capability_snapshot("NVDA")
    # skew / OI / gamma / GEX are paid → must be None, not neutral-filled
    for field in ("put_skew_25d", "strike_oi_concentration", "gamma_concentration", "estimated_dealer_gex"):
        assert snap[field] is None
    assert snap["status"] == "screen_grade"


def test_options_capabilities_flags_match_supported():
    provider = YFinanceFocusOptionsProvider()
    caps = provider.capabilities()
    assert set(caps) == set(OPTIONS_CAPABILITY_FIELDS)
    assert caps["put_call_volume_ratio"] is True
    assert caps["estimated_dealer_gex"] is False


class _FakeBaseProvider:
    def get_iv_metrics(self, symbol):
        return {"current_iv": 0.42, "ivr": 55.0, "ivp": 60.0, "samples": 252}

    def get_options_snapshot(self, symbol):
        return {"put_call_volume_ratio": 0.9}


def test_capability_true_fields_are_actually_populated():
    # Consistency regression: every capability=True field is sourced from the
    # underlying provider (no capability=true + always-None contradiction), and
    # every capability=False field stays None.
    provider = YFinanceFocusOptionsProvider()
    snap = provider.get_capability_snapshot("NVDA", base_provider=_FakeBaseProvider())
    caps = provider.capabilities()
    for field, supported in caps.items():
        if supported:
            assert snap[field] is not None, f"{field} claimed supported but None"
        else:
            assert snap[field] is None, f"{field} not supported but populated"
    assert snap["current_atm_iv"] == 0.42
    assert snap["put_call_volume_ratio"] == 0.9


def test_estimated_gex_includes_assumption_and_confidence():
    provider = YFinanceFocusOptionsProvider()
    gex = provider.estimate_dealer_gex("NVDA", available=False)
    assert gex["estimated"] is True
    assert gex["value"] is None
    assert gex["confidence"] == "none"
    assert "proxy" in gex["assumption"].lower()


def test_estimated_gex_when_available_is_still_estimated_low_confidence():
    provider = YFinanceFocusOptionsProvider()
    gex = provider.estimate_dealer_gex("NVDA", available=True, value=1.5e9)
    assert gex["estimated"] is True
    assert gex["value"] == 1.5e9
    assert gex["confidence"] == "low"


def test_null_estimates_provider_is_honest():
    provider = NullEstimatesProvider()
    est = provider.get_estimates("NVDA")
    assert est["fy1_eps_estimate"] is None
    assert est["ntm_pe"] is None
    assert est["status"] == "not_connected"
    assert est["coverage"] == 0.0


def test_volatility_joint_state_regime_bands():
    provider = PublicVolatilityIndexProvider()
    assert provider.joint_state(15, None, None)["regime"] == "calm"
    assert provider.joint_state(24, None, None)["regime"] == "elevated"
    assert provider.joint_state(35, None, None)["regime"] == "stress"
    assert provider.joint_state(None, None, None)["status"] == "insufficient_data"


def test_volatility_vvix_cor1m_unsupported():
    provider = PublicVolatilityIndexProvider()
    caps = provider.capabilities()
    assert caps["vvix"] is False
    assert caps["cor1m"] is False


def test_volatility_state_carries_as_of_and_freshness(monkeypatch):
    from datetime import date

    import src.data.vix_structure as vs
    from src.focus.providers import PublicVolatilityIndexProvider

    monkeypatch.setattr(vs, "fetch_vix_term_structure", lambda: {"vix": 17.0, "vix9d": 16.0, "vix3m": 18.0})
    monkeypatch.setattr(vs, "fetch_vix_asof", lambda: "2026-07-18")
    state = PublicVolatilityIndexProvider().get_volatility_state(reference_date=date(2026, 7, 20))
    assert state["vix"] == 17.0
    assert state["as_of"] == "2026-07-18"
    assert state["freshness"]["status"] == "fresh"


def test_volatility_stale_as_of_flagged(monkeypatch):
    from datetime import date

    import src.data.vix_structure as vs
    from src.focus.providers import PublicVolatilityIndexProvider

    monkeypatch.setattr(vs, "fetch_vix_term_structure", lambda: {"vix": 17.0})
    monkeypatch.setattr(vs, "fetch_vix_asof", lambda: "2026-06-01")
    state = PublicVolatilityIndexProvider().get_volatility_state(reference_date=date(2026, 7, 20))
    assert state["freshness"]["status"] == "stale"


def test_regime_exposure_cap_bands():
    from src.focus.providers import regime_exposure_cap
    assert regime_exposure_cap("calm")["max_exposure_multiplier"] == 1.0
    assert regime_exposure_cap("elevated")["max_exposure_multiplier"] == 0.5
    assert regime_exposure_cap("stress")["blocks_new_exposure"] is True
    # unknown/missing regime fails closed (blocks new exposure)
    assert regime_exposure_cap(None)["blocks_new_exposure"] is True


def test_options_pressure_partial_evidence_stays_unavailable():
    # finding P1: partial required options data must NOT fall through to confirmed_ok.
    from src.focus.providers import build_options_pressure

    # OI-only: strike concentration alone is not directional → unavailable.
    oi_only = build_options_pressure({"strike_oi_concentration": 0.9, "source": "x"})
    assert oi_only["status"] == "unavailable"
    assert "gamma_flip_proxy" in oi_only["missing_fields"]

    # Absolute skew only (no change, no gamma) → unavailable.
    skew_only = build_options_pressure({"put_skew_25d": 0.05, "source": "x"})
    assert skew_only["status"] == "unavailable"
    assert "put_skew_change" in skew_only["missing_fields"]

    # Mixed partial (gamma present but no skew change) → still unavailable.
    mixed = build_options_pressure(
        {"gamma_flip_proxy": 1.0, "strike_oi_concentration": 0.5, "source": "x"}
    )
    assert mixed["status"] == "unavailable"


def test_options_pressure_confirmed_requires_direction_and_freshness():
    from datetime import date

    from src.focus.providers import build_options_pressure

    complete = {
        "gamma_flip_proxy": 1.0,          # positive → not adverse
        "put_skew_change_5d": -0.01,      # skew easing → not worsening
        "put_skew_25d": 0.04,
        "strike_oi_concentration": 0.4,
        "as_of": "2026-07-18", "source": "paid_provider",
    }
    ok = build_options_pressure(complete, reference_date=date(2026, 7, 20))
    assert ok["status"] == "confirmed_ok"
    assert ok["downside_pressure_confirmed_ok"] is True

    # Same complete evidence but stale as_of → downgraded to unavailable (not confirmation).
    stale = dict(complete, as_of="2026-05-01")
    stale_res = build_options_pressure(stale, reference_date=date(2026, 7, 20))
    assert stale_res["status"] == "unavailable"
    assert "options_evidence_stale" in stale_res["reasons"]

    # Worsening: skew change positive → worsening (blocks add downstream).
    worse = dict(complete, put_skew_change_5d=0.02)
    worse_res = build_options_pressure(worse, reference_date=date(2026, 7, 20))
    assert worse_res["status"] == "worsening"


def test_composite_regime_low_vix_but_damaged_trend_escalates():
    # finding P1: a low VIX (calm base) must NOT keep the regime calm when both
    # leaders are below 200DMA and breadth is broken — escalate + cap exposure.
    from src.focus.providers import composite_market_regime

    index_trend = {
        "QQQ": {"above_50dma": False, "above_200dma": False},
        "SMH": {"above_50dma": False, "above_200dma": False},
        "SOXX": {"above_50dma": False, "above_200dma": False},
    }
    breadth = {"breadth_above_50dma": 0.15, "breadth_above_200dma": 0.1}
    comp = composite_market_regime("calm", index_trend, breadth)
    assert comp["regime"] in ("elevated", "stress")
    assert comp["regime"] != "calm"
    assert comp["escalated_from_vix"] is True
    assert comp["exposure_cap"]["max_exposure_multiplier"] < 1.0


def test_composite_regime_calm_when_healthy():
    from src.focus.providers import composite_market_regime

    index_trend = {
        "QQQ": {"above_50dma": True, "above_200dma": True},
        "SMH": {"above_50dma": True, "above_200dma": True},
        "SOXX": {"above_50dma": True, "above_200dma": True},
    }
    breadth = {"breadth_above_50dma": 0.8, "breadth_above_200dma": 0.75}
    comp = composite_market_regime("calm", index_trend, breadth)
    assert comp["regime"] == "calm"
    assert comp["exposure_cap"]["max_exposure_multiplier"] == 1.0


def test_composite_regime_unknown_when_no_evidence_fails_closed():
    from src.focus.providers import composite_market_regime

    comp = composite_market_regime(None, {}, {}, vix_available=False)
    assert comp["regime"] is None
    assert comp["exposure_cap"]["blocks_new_exposure"] is True


def test_volatility_state_computes_regime_and_preserves_none_inversion(monkeypatch):
    from datetime import date
    import src.data.vix_structure as vs
    from src.focus.providers import PublicVolatilityIndexProvider

    # stress VIX, and vix9d_inverted missing (None) → must stay None, not False
    monkeypatch.setattr(vs, "fetch_vix_term_structure", lambda: {"vix": 33.0, "vix9d": None})
    monkeypatch.setattr(vs, "fetch_vix_asof", lambda: "2026-07-18")
    state = PublicVolatilityIndexProvider().get_volatility_state(reference_date=date(2026, 7, 20))
    assert state["regime"] == "stress"
    assert state["term_inversion"] is None  # preserved, not coerced to False
    assert state["exposure_cap"]["blocks_new_exposure"] is True
