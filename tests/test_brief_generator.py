"""Phase 2.5.2 — brief_generator + InvestorView 單元測試。

涵蓋:
- 4 種 brief cold-start 不崩(全部 mock 外部回 None / 空)
- invalid brief_type raises
- _format_market_regime VIX cold start / 各區間
- _format_sell_put / sell_call / leaps_entry 的條件呈現
- positions 三模式 fallback(mode_3 / 無持倉 / 有 LEAPS)
- classify_market_regime 各 VIX 區間
- HTML escape 防注入
- 任一段失敗不會殺整支 brief
"""

import json
from unittest.mock import patch

import pandas as pd
import pytest

from src.alerts.brief_generator import BriefGenerator
from src.alerts.investor_view import InvestorView


# ── fixtures ──

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
    empty_df = pd.DataFrame()

    with patch("src.alerts.brief_generator.get_latest_price", return_value=None), \
         patch("src.alerts.brief_generator.get_52w_high_low",
               return_value={"high": None, "low": None, "current": None,
                             "pct_from_high": None, "pct_from_low": None}), \
         patch("src.alerts.brief_generator.fetch_history", return_value=empty_df), \
         patch("src.alerts.brief_generator.scan_all_active_etfs", return_value=[]), \
         patch("src.alerts.brief_generator.scan_all_leaps", return_value=[]), \
         patch("src.alerts.brief_generator.scan_all_shorts", return_value=[]), \
         patch("src.alerts.brief_generator.scan_all_hedges", return_value=[]), \
         patch("src.alerts.brief_generator.get_current_drawdown",
               return_value={"drawdown_pct": None, "alert_level": "normal"}), \
         patch("src.alerts.brief_generator.get_upcoming_earnings", return_value=[]), \
         patch("src.alerts.investor_view.fetch_history", return_value=empty_df), \
         patch("src.alerts.investor_view.calc_iv_rank",
               return_value={"ivr": None, "ivp": None, "current_iv": None, "samples": 0}), \
         patch("src.alerts.investor_view.load_positions",
               return_value={"stocks": [], "options": []}), \
         patch("src.alerts.investor_view.calc_option_pnl", return_value={}), \
         patch("src.alerts.investor_view.read_json", return_value={}):
        yield


# ── cold-start: 4 brief types ──

def test_brief_generator_us_eod_cold_start(isolated_data_store):
    msg = BriefGenerator("us_eod").generate()
    assert isinstance(msg, str) and len(msg) > 0
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


def test_next_brief_time_each_type():
    for t in ("us_eod", "tw_eod", "us_premarket", "us_midday"):
        nb = BriefGenerator(t)._next_brief_time()
        assert isinstance(nb, str) and len(nb) > 0


# ── classify_market_regime 各 VIX 區間 ──

@pytest.mark.parametrize("vix,expected_keyword", [
    (None, "缺失"),
    (10.0, "極低波動"),
    (17.0, "低波動"),
    (22.0, "中性"),
    (27.0, "波動上升"),
    (35.0, "恐慌"),
    (50.0, "極端恐慌"),
])
def test_classify_market_regime_buckets(vix, expected_keyword):
    out = InvestorView.classify_market_regime(vix)
    assert expected_keyword in out


# ── _format_market_regime ──

def test_format_market_regime_cold_start(isolated_data_store):
    out = BriefGenerator("us_eod")._format_market_regime()
    assert "整體環境" in out
    assert "n/a" in out


def test_format_market_regime_with_vix():
    """VIX 17 → 低波動,提示等回檔。"""
    with patch("src.alerts.investor_view._vix_from_macro_state", return_value=17.0):
        out = BriefGenerator("us_eod")._format_market_regime()
    assert "17.00" in out
    assert "低波動" in out
    assert "等" in out  # 等 VIX 上升 或 個股深度回檔


# ── InvestorView candidates ──

def _df_with_close(price: float, high: float, n: int = 60) -> pd.DataFrame:
    """造一個近 60 日 daily df,High 包含 high,Close 結尾為 price。"""
    closes = [price * 0.95] * (n - 1) + [price]
    highs = [high] * n
    lows = [price * 0.9] * n
    return pd.DataFrame({"Close": closes, "High": highs, "Low": lows, "Open": closes,
                         "Volume": [1_000_000] * n})


def test_sell_put_candidates_cold_start_no_data(isolated_data_store):
    """所有 quote 失敗 → candidates 仍回 list,每筆 conditions_met=0。"""
    out = InvestorView.get_sell_put_candidates(top_n=3)
    assert isinstance(out, list) and len(out) == 3
    for c in out:
        assert c["conditions_met"] == 0
        assert "等深度回檔" in c["status_text"]


def test_sell_put_candidate_three_conditions_met():
    """造 NVDA: 距 52W 高 -20% / RSI 25 / IVR 70 → 全達。"""
    df = _df_with_close(price=80.0, high=100.0)  # dist = -20%
    with patch("src.alerts.investor_view.fetch_history", return_value=df), \
         patch("src.alerts.investor_view.get_rsi_latest", return_value=25.0), \
         patch("src.alerts.investor_view.calc_iv_rank",
               return_value={"ivr": 70.0, "ivp": 80.0}):
        out = InvestorView.get_sell_put_candidates(top_n=1)
    assert len(out) == 1
    c = out[0]
    assert c["conditions_met"] == 3
    assert "三條件齊備" in c["status_text"]


def test_sell_call_candidates_mode_3_returns_empty(monkeypatch):
    monkeypatch.setattr("src.alerts.investor_view.POSITION_MODE", "mode_3")
    out = InvestorView.get_sell_call_candidates()
    assert out == []


def test_sell_call_candidates_no_real_positions_returns_empty():
    """positions 全是 _example → 不算真實持倉 → []。"""
    fake_pos = {
        "stocks": [{"_example": True, "symbol": "PLTR"}],
        "options": [{"_example": True, "symbol": "MSFT", "type": "long_call"}],
    }
    with patch("src.alerts.investor_view.load_positions", return_value=fake_pos):
        out = InvestorView.get_sell_call_candidates()
    assert out == []


def test_sell_call_candidate_with_real_leaps_close_to_exit():
    """NVDA LEAPS,股價漲到 -2%,RSI 75,獲利 +60% → 三條件齊備。"""
    df = _df_with_close(price=98.0, high=100.0)  # dist = -2%
    fake_pos = {
        "stocks": [],
        "options": [{
            "symbol": "NVDA", "type": "long_call",
            "strike": 80, "expiry": "2027-01-15",
            "contracts": 1, "cost_per_contract": 50.0,
        }],
    }
    with patch("src.alerts.investor_view.load_positions", return_value=fake_pos), \
         patch("src.alerts.investor_view.fetch_history", return_value=df), \
         patch("src.alerts.investor_view.get_rsi_latest", return_value=75.0), \
         patch("src.alerts.investor_view.calc_option_pnl",
               return_value={"pnl_pct": 0.60}):
        out = InvestorView.get_sell_call_candidates()
    assert len(out) == 1
    c = out[0]
    assert c["has_leaps"] is True
    assert c["conditions_met"] == 3


def test_leaps_candidate_three_conditions_met():
    """股價 -30% / RSI 25 / VIX 25 → 三條件齊備。"""
    df = _df_with_close(price=70.0, high=100.0)
    with patch("src.alerts.investor_view.fetch_history", return_value=df), \
         patch("src.alerts.investor_view.get_rsi_latest", return_value=25.0), \
         patch("src.alerts.investor_view._vix_from_macro_state", return_value=25.0):
        out = InvestorView.get_leaps_candidates(top_n=1)
    assert len(out) == 1
    c = out[0]
    assert c["conditions_met"] == 3
    assert "三條件齊備" in c["status_text"]


def test_leaps_candidate_vix_too_low_status():
    """VIX 15 太低 → 該條件 missing 註明「偏低」。"""
    df = _df_with_close(price=70.0, high=100.0)
    with patch("src.alerts.investor_view.fetch_history", return_value=df), \
         patch("src.alerts.investor_view.get_rsi_latest", return_value=25.0), \
         patch("src.alerts.investor_view._vix_from_macro_state", return_value=15.0):
        out = InvestorView.get_leaps_candidates(top_n=1)
    c = out[0]
    assert c["conditions_met"] == 2
    # details 中應提到 VIX 偏低
    assert any("偏低" in d for d in c["details"])


# ── HTML escape ──

def test_html_escape_in_status_text(isolated_data_store):
    """確保 brief 對 symbol 注入無視 — 改造惡意 symbol 進候選。"""
    bad_candidate = {
        "symbol": "<script>alert(1)</script>",
        "price": 100.0, "distance_to_high_pct": -5.0,
        "rsi": 50.0, "ivr": 30.0,
        "conditions_met": 0, "conditions_total": 3,
        "status_text": "全條件未達",
        "details": ["距 52W 高 -5%"],
        "error": None,
    }
    with patch("src.alerts.brief_generator.InvestorView.get_sell_put_candidates",
               return_value=[bad_candidate]):
        msg = BriefGenerator("us_eod").generate()
    assert "<script>" not in msg
    assert "&lt;script&gt;" in msg


# ── 段失敗保護 ──

def test_section_failure_does_not_kill_brief(isolated_data_store):
    """整段炸了 → 該段顯示「資料抓取失敗」,brief 仍生成。"""
    with patch("src.alerts.brief_generator.InvestorView.get_sell_put_candidates",
               side_effect=RuntimeError("yfinance died")):
        msg = BriefGenerator("us_eod").generate()
    assert "美股盤後" in msg
    assert "失敗" in msg or "n/a" in msg


# ── us_eod brief 結構檢查 ──

def test_us_eod_brief_includes_three_views(isolated_data_store):
    """us_eod 必含三大檢視 + 整體環境 + 部位健康 + 事件。"""
    msg = BriefGenerator("us_eod").generate()
    assert "整體環境" in msg
    assert "Sell PUT" in msg
    assert "Sell CALL" in msg
    assert "LEAPS 進場" in msg
    assert "部位健康度" in msg
    assert "今日事件" in msg


def test_tw_eod_brief_includes_add_check(isolated_data_store):
    """tw_eod 必含加碼條件檢視 + 主動 ETF + 美股盤前展望。"""
    msg = BriefGenerator("tw_eod").generate()
    assert "台股當日" in msg
    assert "加碼條件檢視" in msg
    assert "主動 ETF 動向" in msg
    assert "美股盤前展望" in msg


def test_us_premarket_includes_top3_candidates(isolated_data_store):
    msg = BriefGenerator("us_premarket").generate()
    assert "Pre-market 異動" in msg
    assert "Sell PUT 候選" in msg or "Sell PUT" in msg
    assert "Sell CALL 候選" in msg or "Sell CALL" in msg


def test_us_midday_includes_intraday_movers(isolated_data_store):
    msg = BriefGenerator("us_midday").generate()
    assert "今日異動" in msg
    assert "台股展望" in msg


# ── _vix_from_macro_state 真讀檔 path ──

def test_vix_read_from_macro_state_file(isolated_data_store, monkeypatch):
    """確認 InvestorView.get_vix() 真的會讀 layer_macro_regime_state.json。"""
    fake_state = {"indicators": {"vix": {"value": 22.5}}}

    # 直接讓 read_json 回傳 fake_state(覆蓋 autouse fixture)
    with patch("src.alerts.investor_view.read_json", return_value=fake_state):
        vix = InvestorView.get_vix()
    assert vix == 22.5
