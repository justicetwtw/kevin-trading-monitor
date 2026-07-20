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
