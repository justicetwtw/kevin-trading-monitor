"""Focus shadow runner privacy + fail-closed tests(驗收 #7, #8, rollout §13)。"""

import numpy as np
import pandas as pd
import pytest

from src.runners import run_focus_shadow


@pytest.fixture(autouse=True)
def _offline_providers(monkeypatch):
    # Keep the runner deterministic and offline: stub the VIX + options providers.
    from src.focus import providers

    monkeypatch.setattr(
        providers.PublicVolatilityIndexProvider,
        "get_volatility_state",
        lambda self: {"vix": 18.0, "status": "screen_grade"},
    )
    monkeypatch.setattr(
        providers.YFinanceFocusOptionsProvider,
        "get_capability_snapshot",
        lambda self, symbol, base_provider=None: {
            "symbol": symbol, "status": "screen_grade", "put_call_volume_ratio": None,
        },
    )


def _fake_fetch(symbol, period="1y", interval="1d"):
    n = 260
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    closes = np.linspace(80, 120, n)
    return pd.DataFrame(
        {"Close": closes, "High": closes * 1.01, "Low": closes * 0.99,
         "Volume": [1_000_000] * n},
        index=idx,
    )


def _positions():
    return {
        "stocks": [{"symbol": "NVDA", "shares": 100, "last_price": 100.0}],
        "options": [
            {"symbol": "NVDA", "type": "long_put", "strike": 90, "contracts": 2, "expiry": "2027-01-15"},
        ],
    }


def test_shadow_state_when_flag_on_is_public_safe(monkeypatch):
    monkeypatch.setenv("FOCUS_ENGINE_ENABLED", "1")
    state = run_focus_shadow.build_shadow_state(
        holdings=["NVDA"], positions=_positions(), fetch=_fake_fetch
    )
    assert state["enabled"] is True
    # This must not raise: every card key is on the public allow-list.
    run_focus_shadow._assert_public_safe(state)

    data = state["data"]
    assert data["focus_securities"]
    # Exposure summary is aggregate-only
    summary = data["portfolio_exceptions"]
    assert summary["privacy"] == "aggregate_only_no_identifiers"
    text = str(state)
    # No private numeric identifiers from the position book
    assert "strike" not in text
    assert "9000" not in text  # 90 strike * 100 * 2 = 18000 protective; raw notionals absent


def test_shadow_cards_carry_no_private_keys(monkeypatch):
    monkeypatch.setenv("FOCUS_ENGINE_ENABLED", "1")
    state = run_focus_shadow.build_shadow_state(
        holdings=["NVDA"], positions=_positions(), fetch=_fake_fetch
    )
    for card in state["data"]["focus_securities"]:
        leaked = set(card) - run_focus_shadow._ALLOWED_CARD_KEYS
        assert leaked == set()
        assert card["not_a_trade_signal"] is True


def test_assert_public_safe_raises_on_leak():
    bad = {"data": {"focus_securities": [{"symbol": "NVDA", "account_value": 123456}]}}
    try:
        run_focus_shadow._assert_public_safe(bad)
    except ValueError as exc:
        assert "leak" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected a privacy leak to fail closed")


def test_private_holding_outside_universe_never_in_public_payload(monkeypatch):
    # P0 regression: a private holding NOT in the static public universe must
    # never become a public focus card or appear anywhere in the payload.
    monkeypatch.setenv("FOCUS_ENGINE_ENABLED", "1")
    from src.focus.universe import static_focus_symbols

    secret_symbol = "ZZPRIVATE"
    assert secret_symbol not in static_focus_symbols()
    positions = {
        "stocks": [{"symbol": secret_symbol, "shares": 40, "last_price": 12.0}],
        "options": [],
    }
    state = run_focus_shadow.build_shadow_state(
        holdings=[secret_symbol], positions=positions, fetch=_fake_fetch
    )
    run_focus_shadow._assert_public_safe(state)
    blob = str(state)
    assert secret_symbol not in blob
    cards = state["data"]["focus_securities"]
    # Every card instrument comes from the static public universe; the private
    # holding is never among them, and card count == universe size.
    static = set(static_focus_symbols())
    assert all(c["instrument"] in static for c in cards)
    assert secret_symbol not in {c["instrument"] for c in cards}
    assert secret_symbol not in {c["symbol"] for c in cards}
    assert len(cards) == len(static)


def test_degraded_run_when_benchmark_missing(monkeypatch):
    monkeypatch.setenv("FOCUS_ENGINE_ENABLED", "1")

    def fetch_no_benchmark(symbol, period="1y", interval="1d"):
        if symbol in ("QQQ", "SMH"):
            return pd.DataFrame()  # benchmark unavailable
        return _fake_fetch(symbol)

    state = run_focus_shadow.build_shadow_state(
        holdings=[], positions=None, positions_status="ok", fetch=fetch_no_benchmark
    )
    health = state["health"]
    assert health["workflow_status"] == "degraded"
    assert health["degraded"] is True
    assert "benchmark_price_unavailable" in health["error_codes"]


def test_main_enabled_degraded_returns_nonzero(monkeypatch):
    monkeypatch.setenv("FOCUS_ENGINE_ENABLED", "1")
    writes = {}
    import src.storage.state_manager as sm

    monkeypatch.setattr(sm, "write_json", lambda name, data: writes.setdefault(name, data) or True)

    # No POSITIONS_JSON, empty portfolio → unconfigured (partial/degraded), and
    # real VIX/price fetch is unavailable offline → non-zero, not a fake green.
    monkeypatch.setattr(run_focus_shadow, "build_shadow_state", lambda **kw: {
        "schema_version": 1, "enabled": True, "mode": "shadow",
        "health": {"workflow_status": "degraded", "degraded": True, "error_codes": ["x"]},
        "data": {"focus_securities": []},
    })
    rc = run_focus_shadow.main()
    assert rc == 1
    assert writes["focus_engine_state.json"]["health"]["degraded"] is True


def test_main_flag_off_writes_disabled_envelope(monkeypatch):
    monkeypatch.delenv("FOCUS_ENGINE_ENABLED", raising=False)
    writes = {}
    monkeypatch.setattr(
        run_focus_shadow, "write_json", lambda name, data: writes.setdefault(name, data) or True,
        raising=False,
    )
    # write_json is imported inside main(); patch at source module too
    import src.storage.state_manager as sm

    monkeypatch.setattr(sm, "write_json", lambda name, data: writes.setdefault(name, data) or True)
    rc = run_focus_shadow.main()
    assert rc == 0
    assert writes["focus_engine_state.json"]["enabled"] is False
