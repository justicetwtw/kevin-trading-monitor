"""Options provider 介面與 schema 測試(離線,不打網路)。"""

import pytest

from src.data.options_massive import MassiveOptionsProvider
from src.data.options_orats import ORATSOptionsProvider
from src.data.options_provider import (
    OptionsProvider, YFinanceOptionsProvider, get_provider,
)
from src.data.options_tradier import TradierOptionsProvider
from src.models.signal_schema import (
    IV_METRICS_SPEC, OPTIONS_SNAPSHOT_SPEC, validate_record,
)


class FakeProvider(OptionsProvider):
    provider_name = "fake"
    SECRET_NAME = None

    def get_iv_metrics(self, symbol):
        out = self._base_iv_metrics(symbol)
        out.update({"ivr": 42.0, "ivp": 55.0, "current_iv": 0.31, "samples": 100})
        return out

    def get_options_snapshot(self, symbol):
        out = self._base_snapshot(symbol)
        out["put_call_volume_ratio"] = 0.8
        return out


def test_abstract_interface_cannot_instantiate():
    with pytest.raises(TypeError):
        OptionsProvider()


def test_fake_provider_iv_metrics_schema():
    m = FakeProvider().get_iv_metrics("MU")
    assert validate_record(m, IV_METRICS_SPEC, "iv_metrics") == []
    assert m["symbol"] == "MU"
    assert m["source"] == "fake"


def test_fake_provider_snapshot_schema():
    s = FakeProvider().get_options_snapshot("MU")
    assert validate_record(s, OPTIONS_SNAPSHOT_SPEC, "snapshot") == []
    # 免費層不支援的欄位必須是 None,不得硬補
    assert s["put_skew"] is None
    assert s["oi_concentration"] is None
    assert s["unusual_activity"] is None


def test_yfinance_iv_metrics_schema_offline():
    """calc_iv_rank 讀 data_store/iv_history.json,不打網路;schema 必須合法。"""
    m = YFinanceOptionsProvider().get_iv_metrics("NVDA")
    assert validate_record(m, IV_METRICS_SPEC, "iv_metrics") == []
    assert m["source"] == "yfinance"


def test_yfinance_iv_metrics_unknown_symbol_returns_none_not_neutral():
    m = YFinanceOptionsProvider().get_iv_metrics("__NO_SUCH_SYMBOL__")
    assert m["ivr"] is None
    assert m["ivp"] is None


@pytest.mark.parametrize("cls,secret", [
    (ORATSOptionsProvider, "ORATS_API_KEY"),
    (MassiveOptionsProvider, "POLYGON_API_KEY"),
    (TradierOptionsProvider, "TRADIER_ACCESS_TOKEN"),
])
def test_paid_stubs_declare_secret_and_raise(cls, secret, monkeypatch):
    monkeypatch.delenv(secret, raising=False)
    p = cls()
    assert p.SECRET_NAME == secret
    assert p.is_configured() is False
    with pytest.raises(NotImplementedError):
        p.get_iv_metrics("MU")
    with pytest.raises(NotImplementedError):
        p.get_options_snapshot("MU")


def test_get_provider_default_is_free(monkeypatch):
    monkeypatch.delenv("OPTIONS_PROVIDER", raising=False)
    assert isinstance(get_provider(), YFinanceOptionsProvider)


def test_get_provider_unknown_raises():
    with pytest.raises(ValueError):
        get_provider("bloomberg_terminal")
