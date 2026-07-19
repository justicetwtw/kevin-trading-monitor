"""Focus shadow runner privacy + fail-closed tests(驗收 #7, #8, rollout §13)。"""

import numpy as np
import pandas as pd

from src.runners import run_focus_shadow


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
