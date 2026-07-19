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
