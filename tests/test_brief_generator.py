"""Phase 2.5 — brief_generator unit tests。

涵蓋:
- 4 種 brief cold-start 不崩(全部 mock 外部回 None / 空)
- invalid brief_type raises
- _format_layer0 with data / cold start
- _format_top_signals with zero / with data
- _next_brief_time 4 種類型對應正確
- HTML escape 防注入
"""

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from src.alerts.brief_generator import BriefGenerator


@pytest.fixture
def isolated_data_store(tmp_path, monkeypatch):
    fake = tmp_path / "data_store"
    fake.mkdir()
    monkeypatch.setattr("src.storage.state_manager.DATA_STORE_DIR", fake)
    return fake


@pytest.fixture(autouse=True)
def patch_externals():
    """全部 brief test 預設 mock 掉外部抓取(避免真打 yfinance)。
    需要真實值的 test 自己再 patch 覆蓋。"""
    with patch("src.alerts.brief_generator.get_latest_price", return_value=None), \
         patch("src.alerts.brief_generator.get_52w_high_low",
               return_value={"high": None, "low": None, "current": None,
                             "pct_from_high": None, "pct_from_low": None}), \
         patch("src.alerts.brief_generator.fetch_history", return_value=None), \
         patch("src.alerts.brief_generator.scan_all_signals", return_value=[]), \
         patch("src.alerts.brief_generator.scan_twstock_core", return_value=[]), \
         patch("src.alerts.brief_generator.scan_all_active_etfs", return_value=[]), \
         patch("src.alerts.brief_generator.get_upcoming_earnings", return_value=[]):
        yield


def test_brief_generator_us_eod_cold_start(isolated_data_store):
    msg = BriefGenerator("us_eod").generate()
    assert isinstance(msg, str)
    assert len(msg) > 0
    assert "美股盤後" in msg
    assert "下次 brief" in msg


def test_brief_generator_tw_eod_cold_start(isolated_data_store):
    msg = BriefGenerator("tw_eod").generate()
    assert "台股盤後" in msg
    assert "下次 brief" in msg


def test_brief_generator_us_premarket_cold_start(isolated_data_store):
    msg = BriefGenerator("us_premarket").generate()
    assert "美股盤前" in msg
    assert "下次 brief" in msg


def test_brief_generator_us_midday_cold_start(isolated_data_store):
    msg = BriefGenerator("us_midday").generate()
    assert "美股盤中" in msg
    assert "下次 brief" in msg


def test_invalid_brief_type_raises():
    with pytest.raises(ValueError):
        BriefGenerator("nonsense").generate()


def test_layer0_format_with_data(isolated_data_store):
    layer0 = {
        "scan_time": "2026-05-02T07:06:22+00:00",
        "aggregate_modifiers": {
            "sell_call": 5,
            "sell_put": -10,
            "leaps_entry": -15,
            "leaps_entry_veto": False,
        },
        "submodules": {
            "vix_structure": {"snapshot": {"vix": 16.99}},
        },
    }
    (isolated_data_store / "layer0_history.json").write_text(json.dumps(layer0))
    out = BriefGenerator("us_eod")._format_layer0()
    assert "sell_call" in out
    assert "+5" in out
    assert "-10" in out
    assert "-15" in out


def test_layer0_format_cold_start(isolated_data_store):
    out = BriefGenerator("us_eod")._format_layer0()
    assert "資料" in out or "cold" in out.lower() or "n/a" in out.lower()


def test_top_signals_format_with_zero_signals(isolated_data_store):
    out = BriefGenerator("us_eod")._format_top_signals()
    assert isinstance(out, str)
    assert len(out) > 0


def test_top_signals_format_with_data(isolated_data_store):
    fake_signals = [
        {"symbol": "NVDA", "signal_type": "leaps_entry", "final_score": 92,
         "push_threshold": 90, "alert_level": "green", "priority": "P0"},
        {"symbol": "AAPL", "signal_type": "sell_put", "final_score": 88,
         "push_threshold": 85, "alert_level": "yellow", "priority": "P1"},
        {"symbol": "MSFT", "signal_type": "sell_call", "final_score": 75,
         "push_threshold": 80, "alert_level": "white", "priority": "P0"},
    ]
    with patch("src.alerts.brief_generator.scan_all_signals", return_value=fake_signals):
        out = BriefGenerator("us_eod")._format_top_signals()
    assert "NVDA" in out
    assert "AAPL" in out
    assert "MSFT" in out


def test_next_brief_time_each_type(isolated_data_store):
    for t in ("us_eod", "tw_eod", "us_premarket", "us_midday"):
        nb = BriefGenerator(t)._next_brief_time()
        assert isinstance(nb, str)
        assert len(nb) > 0


def test_html_escape_in_brief(isolated_data_store):
    fake_signals = [
        {"symbol": "<script>alert(1)</script>", "signal_type": "leaps_entry",
         "final_score": 92, "push_threshold": 90, "alert_level": "green",
         "priority": "P0"},
    ]
    with patch("src.alerts.brief_generator.scan_all_signals", return_value=fake_signals):
        msg = BriefGenerator("us_eod").generate()
    assert "<script>" not in msg
    assert "&lt;script&gt;" in msg


def test_section_failure_does_not_kill_brief(isolated_data_store):
    """任一段失敗 → 該段顯示「資料抓取失敗」而非整支 brief 死。"""
    with patch("src.alerts.brief_generator.scan_all_signals",
               side_effect=RuntimeError("yfinance died")):
        msg = BriefGenerator("us_eod").generate()
    assert "美股盤後" in msg  # 整支 brief 仍生成
    assert "失敗" in msg or "n/a" in msg.lower()
