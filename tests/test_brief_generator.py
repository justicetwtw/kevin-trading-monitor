"""Phase 2.5.2 + Sprint 2.5.9 — brief_generator + InvestorView unit tests。

涵蓋:
- 6 種 brief cold-start 不崩(全部 mock 外部回 None / 空)
- invalid brief_type raises
- HTML escape 防注入
- InvestorView conditions_total 動態(IVR n/a 不計入)
- status_text 4 種比例
- 結論句 3 種情境(fully / partial / none)+ IVR n/a 提示
- positions 空 → Sell CALL / 部位健康度段不顯示
- positions 有 → 段顯示
- ranking 邏輯(conditions_met 降序、平手 d2h 升序)
- VIX 從 layer0_history 讀
- classify_market_regime 6 區間
- Sprint 2.5.9: tw_open / us_open 結構齊全 + 標題正確
- Sprint 2.5.9: 6 種 brief 都檢查 no unescaped lt
"""

import json
from unittest.mock import patch

import pandas as pd
import pytest

from src.alerts import brief_generator as bg_mod
from src.alerts.brief_generator import BriefGenerator, VALID_BRIEF_TYPES
from src.alerts.investor_view import (
    InvestorView, _ratio_to_status, classify_market_regime,
)


@pytest.fixture
def isolated_data_store(tmp_path, monkeypatch):
    fake = tmp_path / "data_store"
    fake.mkdir()
    monkeypatch.setattr("src.storage.state_manager.DATA_STORE_DIR", fake)
    return fake


@pytest.fixture(autouse=True)
def patch_externals():
    """全部 brief test 預設 mock 掉外部抓取。
    需要真實值的 test 自己再 patch 覆蓋。"""
    with patch("src.alerts.brief_generator.fetch_history", return_value=None), \
         patch("src.alerts.brief_generator.scan_twstock_core", return_value=[]), \
         patch("src.alerts.brief_generator.scan_all_active_etfs", return_value=[]), \
         patch("src.alerts.brief_generator.scan_all_leaps", return_value=[]), \
         patch("src.alerts.brief_generator.scan_all_shorts", return_value=[]), \
         patch("src.alerts.brief_generator.scan_all_hedges", return_value=[]), \
         patch("src.alerts.brief_generator.get_current_drawdown",
               return_value={"drawdown_pct": None, "alert_level": "normal"}), \
         patch("src.alerts.brief_generator.get_upcoming_earnings", return_value=[]), \
         patch("src.alerts.investor_view.fetch_history", return_value=None), \
         patch("src.alerts.investor_view.get_52w_high_low",
               return_value={"current": None, "pct_from_high": None}), \
         patch("src.alerts.investor_view.calc_iv_rank",
               return_value={"ivr": None, "samples": 0}), \
         patch("src.alerts.investor_view.fetch_vix_term_structure",
               return_value={"vix": None}):
        yield


# ============================================================
# Helpers
# ============================================================

def _make_cand(symbol, met, total, d2h=-0.10, ivr=None, vix=None,
               status="僅部分條件達", unmet_codes=None):
    return {
        "symbol": symbol,
        "price": 100.0,
        "distance_to_high_pct": d2h,
        "rsi": 50.0,
        "ivr": ivr,
        "vix": vix,
        "details": ["d1", "d2"],
        "passed_flags": [True] * met + [False] * (total - met),
        "conditions_met": met,
        "conditions_total": total,
        "status_text": status,
        "unmet_codes": unmet_codes or [],
    }


# ============================================================
# Sprint 2.5.9 — VALID_BRIEF_TYPES 6 種
# ============================================================

def test_valid_brief_types_is_six():
    assert set(VALID_BRIEF_TYPES) == {
        "us_eod", "tw_open", "tw_close",
        "us_premarket", "us_open", "us_midday",
    }


def test_old_dst_variants_removed():
    assert "tw_eod" not in VALID_BRIEF_TYPES
    assert "us_premarket_to_intraday" not in VALID_BRIEF_TYPES
    assert "us_midday_to_afterhours" not in VALID_BRIEF_TYPES


# ============================================================
# 6 種 brief cold-start
# ============================================================

def test_us_eod_cold_start(isolated_data_store):
    msg = BriefGenerator("us_eod").generate()
    assert "美股收盤" in msg  # Sprint 2.5.9: 盤後 → 收盤
    assert "下次 brief" in msg


def test_tw_close_cold_start(isolated_data_store):
    msg = BriefGenerator("tw_close").generate()
    assert "台股收盤" in msg
    assert "下次 brief" in msg


def test_tw_open_cold_start(isolated_data_store):
    msg = BriefGenerator("tw_open").generate()
    assert "台股開盤" in msg
    assert "下次 brief" in msg


def test_us_premarket_cold_start(isolated_data_store):
    msg = BriefGenerator("us_premarket").generate()
    assert "美股盤前" in msg
    assert "下次 brief" in msg


def test_us_open_cold_start(isolated_data_store):
    msg = BriefGenerator("us_open").generate()
    assert "美股開盤" in msg
    assert "下次 brief" in msg


def test_us_midday_cold_start(isolated_data_store):
    msg = BriefGenerator("us_midday").generate()
    assert "美股盤中" in msg
    assert "下次 brief" in msg


def test_invalid_brief_type_raises():
    with pytest.raises(ValueError):
        BriefGenerator("nonsense").generate()


def test_old_tw_eod_raises():
    """舊 tw_eod 名稱應 raise(已 rename 為 tw_close)。"""
    with pytest.raises(ValueError):
        BriefGenerator("tw_eod").generate()


def test_next_brief_time_each_type(isolated_data_store):
    for t in VALID_BRIEF_TYPES:
        nb = BriefGenerator(t)._next_brief_time()
        assert isinstance(nb, str) and len(nb) > 0


# ============================================================
# Sprint 2.5.9 — 標題正確
# ============================================================

def test_brief_titles_correct(isolated_data_store):
    """6 種 brief 標題符合 spec(us_eod 是「收盤」不是「盤後」)。"""
    titles = bg_mod._BRIEF_TITLE
    assert titles["us_eod"] == "📊 美股收盤 brief"
    assert titles["tw_open"] == "🇹🇼 台股開盤 brief"
    assert titles["tw_close"] == "🇹🇼 台股收盤 brief"
    assert titles["us_premarket"] == "🌎 美股盤前 brief"
    assert titles["us_open"] == "🚀 美股開盤 brief"
    assert titles["us_midday"] == "🌃 美股盤中 brief"


# ============================================================
# Sprint 2.5.9 — tw_open / us_open 結構齊全
# ============================================================

def test_tw_open_brief_structure(isolated_data_store):
    """tw_open brief 應含:整體環境 + 美股昨夜收盤 + 台股盤前展望 + 今日台股事件 + 台股開盤判斷。"""
    msg = BriefGenerator("tw_open").generate()
    assert "整體環境" in msg
    assert "美股當日完整收盤" in msg  # 美股昨夜收盤
    assert "美股盤前展望" in msg  # 台股盤前展望(用 ES + TSM)
    assert "今日台股事件" in msg
    assert "台股開盤判斷" in msg  # 結論段


def test_us_open_brief_structure(isolated_data_store):
    """us_open brief 應含:整體環境 + Pre-market 異動 + Sell PUT + LEAPS + 今日事件 + 開盤計畫。"""
    msg = BriefGenerator("us_open").generate()
    assert "整體環境" in msg
    assert "Pre-market 異動" in msg
    assert "Sell PUT 機會檢視" in msg
    assert "LEAPS 進場檢視" in msg
    assert "今日事件" in msg
    assert "美股開盤計畫" in msg


# ============================================================
# 段失敗不殺整支 brief
# ============================================================

def test_section_failure_does_not_kill_brief(isolated_data_store):
    """任一段失敗 → 該段顯示「資料抓取失敗」而非整支 brief 死。"""
    with patch.object(bg_mod.InvestorView, "get_sell_put_candidates",
                      side_effect=RuntimeError("api died")):
        msg = BriefGenerator("us_eod").generate()
    assert "美股收盤" in msg
    assert "失敗" in msg


# ============================================================
# HTML escape
# ============================================================

def test_html_escape_in_candidates(isolated_data_store):
    bad = _make_cand("<script>alert(1)</script>", 1, 2)
    with patch.object(bg_mod.InvestorView, "get_sell_put_candidates",
                      return_value=[bad]):
        msg = BriefGenerator("us_eod").generate()
    assert "<script>" not in msg or "&lt;script&gt;" in msg
    assert "&lt;script&gt;" in msg


# ============================================================
# InvestorView: conditions_total 動態
# ============================================================

def test_sell_put_ivr_none_excludes_from_total(isolated_data_store):
    with patch("src.alerts.investor_view.get_52w_high_low",
               return_value={"current": 100.0, "pct_from_high": -0.20}), \
         patch("src.alerts.investor_view.calc_iv_rank",
               return_value={"ivr": None, "samples": 0}):
        df = pd.DataFrame({"Close": [100.0] * 30})
        with patch("src.alerts.investor_view.fetch_history", return_value=df), \
             patch("src.alerts.investor_view.get_rsi_latest", return_value=20.0):
            view = InvestorView()
            cands = view.get_sell_put_candidates(top_n=3)
    assert len(cands) > 0
    for c in cands:
        assert c["conditions_total"] == 2
        assert sum(1 for f in c["passed_flags"] if f is None) == 1


def test_sell_put_ivr_present_total_3(isolated_data_store):
    with patch("src.alerts.investor_view.get_52w_high_low",
               return_value={"current": 100.0, "pct_from_high": -0.20}), \
         patch("src.alerts.investor_view.calc_iv_rank",
               return_value={"ivr": 50.0, "samples": 100}):
        df = pd.DataFrame({"Close": [100.0] * 30})
        with patch("src.alerts.investor_view.fetch_history", return_value=df), \
             patch("src.alerts.investor_view.get_rsi_latest", return_value=20.0):
            view = InvestorView()
            cands = view.get_sell_put_candidates(top_n=3)
    for c in cands:
        assert c["conditions_total"] == 3
        assert c["conditions_met"] == 3


def test_leaps_vix_none_excludes_from_total(isolated_data_store):
    with patch("src.alerts.investor_view.get_52w_high_low",
               return_value={"current": 100.0, "pct_from_high": -0.30}), \
         patch("src.alerts.investor_view.fetch_vix_term_structure",
               return_value={"vix": None}):
        df = pd.DataFrame({"Close": [100.0] * 30})
        with patch("src.alerts.investor_view.fetch_history", return_value=df), \
             patch("src.alerts.investor_view.get_rsi_latest", return_value=20.0):
            view = InvestorView()
            cands = view.get_leaps_candidates(top_n=3)
    for c in cands:
        assert c["conditions_total"] == 2
        assert c["vix"] is None


# ============================================================
# InvestorView: status_text 比例
# ============================================================

def test_ratio_to_status_full():
    assert _ratio_to_status(3, 3) == "全條件達標 — 強烈候選"
    assert _ratio_to_status(2, 2) == "全條件達標 — 強烈候選"


def test_ratio_to_status_majority():
    assert _ratio_to_status(2, 3) == "多數條件達 — 候選"
    assert _ratio_to_status(1, 2) == "多數條件達 — 候選"


def test_ratio_to_status_partial():
    assert _ratio_to_status(1, 3) == "僅部分條件達"


def test_ratio_to_status_none():
    assert _ratio_to_status(0, 3) == "全條件未達"
    assert _ratio_to_status(0, 2) == "全條件未達"


# ============================================================
# 結論句 3 情境
# ============================================================

def test_conclusion_fully_met(isolated_data_store):
    cands = [
        _make_cand("NVDA", 3, 3, status="全條件達標 — 強烈候選"),
        _make_cand("META", 1, 3),
    ]
    msg = bg_mod._build_conclusion(cands, "sell_put")
    assert "結論" in msg
    assert "NVDA" in msg
    assert "齊備" in msg or "強烈候選" in msg


def test_conclusion_partial_met(isolated_data_store):
    cands = [
        _make_cand("NVDA", 1, 3, unmet_codes=["rsi_too_high", "ivr_too_low"]),
        _make_cand("META", 1, 3, unmet_codes=["rsi_too_high", "ivr_too_low"]),
    ]
    msg = bg_mod._build_conclusion(cands, "sell_put")
    assert "結論" in msg
    assert "接近接貨區" in msg
    assert ("NVDA" in msg or "META" in msg)
    assert "仍有條件未滿足" not in msg


def test_conclusion_partial_wait_rsi(isolated_data_store):
    cands = [
        _make_cand("A", 2, 3, unmet_codes=["rsi_too_high"]),
        _make_cand("B", 2, 3, unmet_codes=["rsi_too_high"]),
    ]
    msg = bg_mod._build_conclusion(cands, "sell_put")
    assert "等 RSI 過低" in msg


def test_conclusion_partial_wait_distance(isolated_data_store):
    cands = [
        _make_cand("A", 2, 3, unmet_codes=["distance_not_enough"]),
        _make_cand("B", 2, 3, unmet_codes=["distance_not_enough"]),
    ]
    msg = bg_mod._build_conclusion(cands, "sell_put")
    assert "等股價深度回檔" in msg


def test_conclusion_partial_truly_mixed(isolated_data_store):
    cands = [
        _make_cand("A", 2, 3, unmet_codes=["rsi_too_high"]),
        _make_cand("B", 2, 3, unmet_codes=["distance_not_enough"]),
        _make_cand("C", 2, 3, unmet_codes=["ivr_too_low"]),
    ]
    msg = bg_mod._build_conclusion(cands, "sell_put")
    assert "等多重條件成熟" in msg


def test_conclusion_all_none_met(isolated_data_store):
    cands = [
        _make_cand("NVDA", 0, 3),
        _make_cand("META", 0, 3),
    ]
    msg = bg_mod._build_conclusion(cands, "sell_put")
    assert "等市場回檔" in msg


def test_conclusion_partial_with_all_ivr_none_warning(isolated_data_store):
    cands = [
        _make_cand("NVDA", 1, 2, ivr=None, unmet_codes=["rsi_too_high"]),
        _make_cand("META", 1, 2, ivr=None, unmet_codes=["rsi_too_high"]),
    ]
    msg = bg_mod._build_conclusion(cands, "sell_put")
    assert "IVR" in msg and ("Phase 3" in msg or "IV 累積" in msg)


def test_conclusion_leaps_all_vix_none_warning(isolated_data_store):
    cands = [
        _make_cand("NVDA", 1, 2, vix=None, unmet_codes=["rsi_too_high"]),
        _make_cand("META", 1, 2, vix=None, unmet_codes=["rsi_too_high"]),
    ]
    msg = bg_mod._build_conclusion(cands, "leaps")
    assert "VIX" in msg


def test_conclusion_empty_candidates(isolated_data_store):
    msg = bg_mod._build_conclusion([], "sell_put")
    assert "無" in msg or "結論" in msg


# ============================================================
# positions 空 vs 有
# ============================================================

def test_positions_empty_skips_sell_call_and_health(isolated_data_store, tmp_path):
    pos = {
        "stocks": [{"_example": True, "symbol": "PLTR", "shares": 100}],
        "options": [{"_example": True, "symbol": "MSFT", "type": "long_call"}],
    }
    (isolated_data_store / "positions.json").write_text(
        json.dumps(pos), encoding="utf-8"
    )
    msg = BriefGenerator("us_eod").generate()
    assert "Sell CALL 機會檢視" not in msg
    assert "部位健康度" not in msg


def test_positions_with_real_holding_shows_sell_call_and_health(
    isolated_data_store, tmp_path,
):
    pos = {
        "stocks": [],
        "options": [{
            "id": "NVDA_140C_2027",
            "symbol": "NVDA",
            "type": "long_call",
            "strike": 140.0,
            "expiry": "2027-01-15",
            "contracts": 1,
            "cost_per_contract": 50.0,
            "opened_date": "2026-01-15",
        }],
    }
    (isolated_data_store / "positions.json").write_text(
        json.dumps(pos), encoding="utf-8"
    )
    msg = BriefGenerator("us_eod").generate()
    assert "Sell CALL 機會檢視" in msg
    assert "部位健康度" in msg


# ============================================================
# Ranking
# ============================================================

def test_rank_by_conditions_met_descending(isolated_data_store):
    raw = [
        _make_cand("A", 1, 3, d2h=-0.10),
        _make_cand("B", 3, 3, d2h=-0.10),
        _make_cand("C", 2, 3, d2h=-0.10),
    ]
    out = InvestorView._rank_top_n(raw, top_n=3)
    assert [c["symbol"] for c in out] == ["B", "C", "A"]


def test_rank_tiebreak_by_deeper_pullback(isolated_data_store):
    raw = [
        _make_cand("A", 2, 3, d2h=-0.05),
        _make_cand("B", 2, 3, d2h=-0.30),
        _make_cand("C", 2, 3, d2h=-0.15),
    ]
    out = InvestorView._rank_top_n(raw, top_n=3)
    assert [c["symbol"] for c in out] == ["B", "C", "A"]


def test_rank_top_n_truncates(isolated_data_store):
    raw = [_make_cand(f"X{i}", i % 4, 3) for i in range(10)]
    out = InvestorView._rank_top_n(raw, top_n=3)
    assert len(out) == 3


# ============================================================
# classify_market_regime
# ============================================================

@pytest.mark.parametrize("vix,expected", [
    (10.0, "極低波動 (vol crush)"),
    (13.0, "低波動"),
    (17.0, "正常"),
    (22.0, "略偏高"),
    (27.0, "高波動"),
    (35.0, "極高波動 (panic)"),
    (None, "n/a"),
])
def test_classify_market_regime(vix, expected):
    assert classify_market_regime(vix) == expected


# ============================================================
# VIX 從 layer0_history 讀
# ============================================================

def test_vix_read_from_layer0_history(isolated_data_store):
    layer0 = {
        "submodules": {
            "vix_structure": {"snapshot": {"vix": 22.5}},
        },
    }
    (isolated_data_store / "layer0_history.json").write_text(
        json.dumps(layer0), encoding="utf-8"
    )
    view = InvestorView()
    assert view._vix() == 22.5


def test_vix_fallback_when_layer0_missing(isolated_data_store):
    with patch("src.alerts.investor_view.fetch_vix_term_structure",
               return_value={"vix": 18.7}):
        view = InvestorView()
        assert view._vix() == 18.7


# ============================================================
# us_eod / us_midday / us_premarket: 段順序 + 不重複
# ============================================================

def test_us_midday_no_duplicate_macro_section(isolated_data_store):
    msg = BriefGenerator("us_midday").generate()
    assert msg.count("整體環境") == 1
    assert "美股當日" not in msg


def test_us_premarket_no_duplicate_macro_section(isolated_data_store):
    msg = BriefGenerator("us_premarket").generate()
    assert msg.count("整體環境") == 1
    assert "美股當日" not in msg


def test_us_eod_section_order(isolated_data_store):
    msg = BriefGenerator("us_eod").generate()
    idx_env = msg.find("整體環境")
    idx_put = msg.find("Sell PUT 機會檢視")
    idx_leaps = msg.find("LEAPS 進場檢視")
    idx_events = msg.find("今日事件")
    assert idx_env != -1 and idx_put != -1 and idx_leaps != -1 and idx_events != -1
    assert idx_env < idx_put < idx_leaps < idx_events
    assert "Sell CALL 機會檢視" not in msg
    assert "部位健康度" not in msg


# ============================================================
# tw_close (舊 tw_eod) 加碼條件 + TSM 推估
# ============================================================

def test_tw_signals_show_distance_and_rsi(isolated_data_store):
    fake_sigs = [{
        "symbol": "00631L.TW",
        "name": "元大台灣 50 正 2",
        "price": 30.94,
        "pct_from_52w_high": -0.05,
        "rsi14_weekly": 60.0,
        "tier": None,
        "action": "觀望",
    }]
    with patch("src.alerts.brief_generator.scan_twstock_core",
               return_value=fake_sigs):
        msg = BriefGenerator("tw_close").generate()
    assert "加碼條件檢視" in msg
    assert "距 52W 高" in msg
    assert "週 RSI(14)" in msg
    assert "A 級需" in msg
    assert ("不符合" in msg) or ("接近 A 級" in msg) or ("符合" in msg)


def test_tw_signals_tier_a_status(isolated_data_store):
    fake_sigs = [{
        "symbol": "00631L.TW",
        "name": "元大台灣 50 正 2",
        "price": 28.0,
        "pct_from_52w_high": -0.15,
        "rsi14_weekly": 35.0,
        "tier": "A",
        "action": "預備子彈 25% 加碼",
    }]
    with patch("src.alerts.brief_generator.scan_twstock_core",
               return_value=fake_sigs):
        msg = BriefGenerator("tw_close").generate()
    assert "符合 A 級" in msg


def test_tw_signals_near_a_status(isolated_data_store):
    fake_sigs = [{
        "symbol": "00631L.TW",
        "name": "元大",
        "price": 30.0,
        "pct_from_52w_high": -0.07,
        "rsi14_weekly": 45.0,
        "tier": None,
        "action": "觀望",
    }]
    with patch("src.alerts.brief_generator.scan_twstock_core",
               return_value=fake_sigs):
        msg = BriefGenerator("tw_close").generate()
    assert "接近 A 級" in msg


def test_tw_close_premarket_preview_uses_tsm_with_estimate(isolated_data_store):
    def fake_day_change(sym):
        if sym == "ES=F":
            return 5800.0, 0.002
        if sym == "TSM":
            return 250.34, 0.012
        return None, None
    with patch("src.alerts.brief_generator._day_change",
               side_effect=fake_day_change):
        msg = BriefGenerator("tw_close").generate()
    assert "TSM ADR" in msg
    assert "預期 2330 隔日" in msg
    assert "TSM × 0.7~1.0" in msg
    preview_start = msg.find("🌎 美股盤前展望")
    preview_end = msg.find("下次 brief", preview_start)
    preview_section = msg[preview_start:preview_end]
    assert "NVDA" not in preview_section


# ============================================================
# Sprint 2.5.9 — tw_open 美股昨夜收盤段
# ============================================================

def test_tw_open_includes_us_close_summary(isolated_data_store):
    """tw_open 應有 SPY/QQQ/DIA/VIX 收盤段(美股昨夜)。"""
    msg = BriefGenerator("tw_open").generate()
    assert "SPY 收盤" in msg
    assert "QQQ 收盤" in msg
    assert "DIA 收盤" in msg
    assert "VIX 收盤" in msg


def test_tw_open_conclusion_uses_us_close_data(isolated_data_store):
    """tw_open 結論基於美股昨夜 SPY/QQQ 平均漲跌。"""
    def fake_day_change(sym):
        if sym in ("SPY", "QQQ", "DIA"):
            return 500.0, 0.012  # +1.2%
        if sym == "TSM":
            return 250.0, 0.015
        return None, None
    with patch("src.alerts.brief_generator._day_change",
               side_effect=fake_day_change):
        msg = BriefGenerator("tw_open").generate()
    assert "台股開盤判斷" in msg
    assert "美股昨夜收紅" in msg or "偏多" in msg


def test_tw_open_conclusion_handles_missing_us_data(isolated_data_store):
    """tw_open 美股資料全 None → 結論段不崩。"""
    msg = BriefGenerator("tw_open").generate()  # patch_externals 已 mock 全 None
    assert "台股開盤判斷" in msg
    # 應有 fallback 文字或無法判斷提示
    assert ("無法判斷" in msg) or ("資料缺" in msg) or ("觀望" in msg)


# ============================================================
# Sprint 2.5.9 — us_open 結論
# ============================================================

def test_us_open_conclusion_present(isolated_data_store):
    msg = BriefGenerator("us_open").generate()
    assert "美股開盤計畫" in msg


# ============================================================
# Sprint 2.5.7 hotfix — HTML escape 防 Telegram parse error
# Sprint 2.5.9 — 6 種 brief 都檢查
# ============================================================

import re


def _assert_no_unescaped_lt(msg: str):
    bad = re.search(r'<\s*\d', msg)
    assert bad is None, f"unescaped `< 數字` at offset {bad.start()}: ...{msg[max(0,bad.start()-30):bad.end()+30]}..."
    illegal_tag = re.search(r'<[^/!a-zA-Z]', msg)
    assert illegal_tag is None, f"unescaped `<` (not a tag) at offset {illegal_tag.start()}"


@pytest.mark.parametrize("brief_type", VALID_BRIEF_TYPES)
def test_brief_no_unescaped_lt_cold_start(isolated_data_store, brief_type):
    """6 種 brief cold-start 輸出不該含未 escape 的 `< 數字`。"""
    msg = BriefGenerator(brief_type).generate()
    _assert_no_unescaped_lt(msg)


def test_tw_close_twstock_signals_escape_lt(isolated_data_store):
    """tw_close (舊 tw_eod) 的 twstock 加碼條件檢視段含 `(A 級需 < 40)` 文字 → 必須 escape。"""
    fake_sigs = [
        {
            "symbol": "00631L.TW",
            "name": "元大台灣 50 正 2",
            "price": 30.94,
            "pct_from_52w_high": -0.05,
            "rsi14_weekly": 80.0,
            "tier": None,
            "action": "觀望",
        },
        {
            "symbol": "2330.TW",
            "name": "台積電",
            "price": 1000.0,
            "pct_from_52w_high": -0.20,
            "rsi14_weekly": 30.0,
            "tier": "A",
            "action": "預備子彈 25% 加碼",
        },
    ]
    with patch("src.alerts.brief_generator.scan_twstock_core",
               return_value=fake_sigs):
        msg = BriefGenerator("tw_close").generate()
    assert "週 RSI(14) 80" in msg
    assert "週 RSI(14) 30" in msg
    _assert_no_unescaped_lt(msg)
    assert "&lt;" in msg


def test_legitimate_html_tags_preserved(isolated_data_store):
    msg = BriefGenerator("us_eod").generate()
    assert "<b>" in msg
    assert "</b>" in msg
    assert "<i>" in msg
    assert "</i>" in msg
