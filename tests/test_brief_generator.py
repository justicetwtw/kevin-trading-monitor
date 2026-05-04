"""Phase 2.5.2 — brief_generator + InvestorView unit tests。

涵蓋:
- 4 種 brief cold-start 不崩(全部 mock 外部回 None / 空)
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
"""

import json
from unittest.mock import patch

import pandas as pd
import pytest

from src.alerts import brief_generator as bg_mod
from src.alerts.brief_generator import BriefGenerator
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
# Helpers (sample candidate dicts for unit testing pure logic)
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
# 4 種 brief cold-start
# ============================================================

def test_us_eod_cold_start(isolated_data_store):
    msg = BriefGenerator("us_eod").generate()
    assert "美股盤後" in msg
    assert "下次 brief" in msg
    assert isinstance(msg, str) and len(msg) > 0


def test_tw_eod_cold_start(isolated_data_store):
    msg = BriefGenerator("tw_eod").generate()
    assert "台股盤後" in msg
    assert "下次 brief" in msg


def test_us_premarket_cold_start(isolated_data_store):
    msg = BriefGenerator("us_premarket").generate()
    assert "美股盤前" in msg
    assert "下次 brief" in msg


def test_us_midday_cold_start(isolated_data_store):
    msg = BriefGenerator("us_midday").generate()
    assert "美股盤中" in msg
    assert "下次 brief" in msg


def test_invalid_brief_type_raises():
    with pytest.raises(ValueError):
        BriefGenerator("nonsense").generate()


def test_next_brief_time_each_type(isolated_data_store):
    for t in ("us_eod", "tw_eod", "us_premarket", "us_midday"):
        nb = BriefGenerator(t)._next_brief_time()
        assert isinstance(nb, str) and len(nb) > 0


# ============================================================
# 段失敗不殺整支 brief
# ============================================================

def test_section_failure_does_not_kill_brief(isolated_data_store):
    """任一段失敗 → 該段顯示「資料抓取失敗」而非整支 brief 死。"""
    with patch.object(bg_mod.InvestorView, "get_sell_put_candidates",
                      side_effect=RuntimeError("api died")):
        msg = BriefGenerator("us_eod").generate()
    assert "美股盤後" in msg  # 整支 brief 仍生成
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
    """IVR n/a → conditions_total = 2(不是 3)。"""
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
        # IVR None → conditions_total 應 = 2
        assert c["conditions_total"] == 2
        # passed_flags 應有 1 個 None
        assert sum(1 for f in c["passed_flags"] if f is None) == 1


def test_sell_put_ivr_present_total_3(isolated_data_store):
    """IVR 有值 → conditions_total = 3。"""
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
        # 全條件達標
        assert c["conditions_met"] == 3


def test_leaps_vix_none_excludes_from_total(isolated_data_store):
    """VIX n/a → LEAPS conditions_total = 2(d2h + RSI)。"""
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
        # VIX 應該是 None,passed_flag 應該是 None
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
    """partial_met → 「接近接貨區,等 X」(不再是冗餘的「部分條件達, 仍有條件未滿足」)。"""
    cands = [
        _make_cand("NVDA", 1, 3, unmet_codes=["rsi_too_high", "ivr_too_low"]),
        _make_cand("META", 1, 3, unmet_codes=["rsi_too_high", "ivr_too_low"]),
    ]
    msg = bg_mod._build_conclusion(cands, "sell_put")
    assert "結論" in msg
    assert "接近接貨區" in msg
    assert ("NVDA" in msg or "META" in msg)
    # 不再出現冗餘文字
    assert "仍有條件未滿足" not in msg


def test_conclusion_partial_wait_rsi(isolated_data_store):
    """所有 partial_met 都缺 RSI → 「等 RSI 過低」。"""
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
    """每筆 partial_met 缺不同條件 → 「等多重條件成熟」。"""
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
    """sell_put 全部 IVR=None 時,結論應加 IV history 提示。"""
    cands = [
        _make_cand("NVDA", 1, 2, ivr=None, unmet_codes=["rsi_too_high"]),
        _make_cand("META", 1, 2, ivr=None, unmet_codes=["rsi_too_high"]),
    ]
    msg = bg_mod._build_conclusion(cands, "sell_put")
    assert "IVR" in msg and ("Phase 3" in msg or "IV 累積" in msg)


def test_conclusion_leaps_all_vix_none_warning(isolated_data_store):
    """leaps 全部 VIX=None 時,結論應加 VIX 提示。"""
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
# positions 空 vs 有 → Sell CALL / 部位健康度顯示
# ============================================================

def test_positions_empty_skips_sell_call_and_health(isolated_data_store, tmp_path):
    """全 _example positions → Sell CALL 段、部位健康度段都不顯示。"""
    # 寫入全 _example positions(就用預設範本即可)
    pos = {
        "stocks": [{"_example": True, "symbol": "PLTR", "shares": 100}],
        "options": [{"_example": True, "symbol": "MSFT", "type": "long_call"}],
    }
    (isolated_data_store / "positions.json").write_text(
        json.dumps(pos), encoding="utf-8"
    )
    # 其他必要的 mock 已在 patch_externals 處理
    msg = BriefGenerator("us_eod").generate()
    # 不應出現 Sell CALL 或 部位健康度 段標題
    assert "Sell CALL 機會檢視" not in msg
    assert "部位健康度" not in msg


def test_positions_with_real_holding_shows_sell_call_and_health(
    isolated_data_store, tmp_path,
):
    """真實持倉 → Sell CALL + 部位健康度 段都顯示。"""
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
    """conditions_met 高的排前。"""
    raw = [
        _make_cand("A", 1, 3, d2h=-0.10),
        _make_cand("B", 3, 3, d2h=-0.10),
        _make_cand("C", 2, 3, d2h=-0.10),
    ]
    out = InvestorView._rank_top_n(raw, top_n=3)
    assert [c["symbol"] for c in out] == ["B", "C", "A"]


def test_rank_tiebreak_by_deeper_pullback(isolated_data_store):
    """conditions_met 平手 → distance_to_high_pct 升序(更深回檔優先,負數越小越前)。"""
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
    """layer0_history 不存在 → 回退到 fetch_vix_term_structure。"""
    with patch("src.alerts.investor_view.fetch_vix_term_structure",
               return_value={"vix": 18.7}):
        view = InvestorView()
        assert view._vix() == 18.7


# ============================================================
# 整合:us_eod 段順序
# ============================================================

def test_us_midday_no_duplicate_macro_section(isolated_data_store):
    """us_midday 不再有重複的「📈 美股當日」段(整體環境已含 SPY/QQQ/VIX)。"""
    msg = BriefGenerator("us_midday").generate()
    # 「整體環境」段標題只出現一次,「美股當日」段標題不應出現
    assert msg.count("整體環境") == 1
    assert "美股當日" not in msg


def test_us_premarket_no_duplicate_macro_section(isolated_data_store):
    """us_premarket 同樣不應有重複的美股當日段。"""
    msg = BriefGenerator("us_premarket").generate()
    assert msg.count("整體環境") == 1
    assert "美股當日" not in msg


# ============================================================
# Phase 2.5.6 — DST / timing 變體
# ============================================================

def test_us_premarket_to_intraday_cold_start(isolated_data_store):
    """DST 變體:us_premarket → intraday brief 不崩 + 含開盤標註。"""
    msg = BriefGenerator("us_premarket_to_intraday").generate()
    assert "美股開盤即時 brief" in msg
    assert "開盤即時異動" in msg
    assert "美股已開盤" in msg
    assert "下次 brief" in msg


def test_us_midday_to_afterhours_cold_start(isolated_data_store):
    """DST 變體:us_midday → afterhours brief 不崩 + 含收盤標註。"""
    msg = BriefGenerator("us_midday_to_afterhours").generate()
    assert "美股盤後早晨 brief" in msg
    assert "美股當日完整收盤" in msg
    assert "美股已收盤" in msg
    assert "下次 brief" in msg


def test_us_midday_to_afterhours_includes_close_summary(isolated_data_store):
    """afterhours 變體應有 SPY/QQQ/DIA/VIX 收盤總覽。"""
    msg = BriefGenerator("us_midday_to_afterhours").generate()
    assert "SPY 收盤" in msg
    assert "QQQ 收盤" in msg
    assert "DIA 收盤" in msg
    assert "VIX 收盤" in msg


def test_dst_variants_in_valid_types():
    """新增變體應被視為合法 brief_type。"""
    from src.alerts.brief_generator import VALID_BRIEF_TYPES
    assert "us_premarket_to_intraday" in VALID_BRIEF_TYPES
    assert "us_midday_to_afterhours" in VALID_BRIEF_TYPES


# ============================================================
# tw_eod 加碼條件檢視 + 美股盤前 TSM 推估
# ============================================================

def test_tw_signals_show_distance_and_rsi(isolated_data_store):
    """tw_eod 應顯示距 52W 高 / 週 RSI / A 級門檻 / 狀態,不只 「tier=— 觀望」。"""
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
        msg = BriefGenerator("tw_eod").generate()
    assert "加碼條件檢視" in msg
    assert "距 52W 高" in msg
    assert "週 RSI(14)" in msg
    assert "A 級需" in msg
    # 狀態行:應提示「不符合」/「接近 A 級」/「符合 X 級」
    assert ("不符合" in msg) or ("接近 A 級" in msg) or ("符合" in msg)


def test_tw_signals_tier_a_status(isolated_data_store):
    """tier=A 時 → 狀態:符合 A 級。"""
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
        msg = BriefGenerator("tw_eod").generate()
    assert "符合 A 級" in msg


def test_tw_signals_near_a_status(isolated_data_store):
    """距高 -7%(A 需 -10%)→ 接近 A 級門檻。"""
    fake_sigs = [{
        "symbol": "00631L.TW",
        "name": "元大",
        "price": 30.0,
        "pct_from_52w_high": -0.07,  # 接近 A
        "rsi14_weekly": 45.0,        # 接近 A
        "tier": None,
        "action": "觀望",
    }]
    with patch("src.alerts.brief_generator.scan_twstock_core",
               return_value=fake_sigs):
        msg = BriefGenerator("tw_eod").generate()
    assert "接近 A 級" in msg


def test_tw_eod_premarket_preview_uses_tsm_with_estimate(isolated_data_store):
    """tw_eod 美股盤前展望:用 TSM ADR(對應 2330)+ 漲跌 + 推估 2330 隔日。"""
    # ES + TSM 都回 (price, chg)
    def fake_day_change(sym):
        if sym == "ES=F":
            return 5800.0, 0.002
        if sym == "TSM":
            return 250.34, 0.012  # +1.2%
        return None, None
    with patch("src.alerts.brief_generator._day_change",
               side_effect=fake_day_change):
        msg = BriefGenerator("tw_eod").generate()
    assert "TSM ADR" in msg
    assert "預期 2330 隔日" in msg
    assert "TSM × 0.7~1.0" in msg
    # NVDA 應已從 preview 移掉(它原本對應不到 2330)
    # 注意:Sell PUT / LEAPS 段內可能仍有 NVDA(那些段在 us_eod 才有,tw_eod 沒)
    # 在 tw_eod brief 內 NVDA 不應出現
    # 但 fake_day_change 內若沒 NVDA mock,也不會印
    # 這裡用更弱的 assertion:preview 內標題不再對 NVDA
    # (找到 "🌎 美股盤前展望" 起到「下次 brief」之間的段)
    preview_start = msg.find("🌎 美股盤前展望")
    preview_end = msg.find("下次 brief", preview_start)
    preview_section = msg[preview_start:preview_end]
    assert "NVDA" not in preview_section


def test_us_eod_section_order(isolated_data_store):
    """整體環境 → Sell PUT → (Sell CALL skip if empty) → LEAPS → (健康度 skip) → 今日事件。"""
    msg = BriefGenerator("us_eod").generate()
    # Cold-start 下 positions 空,Sell CALL / 健康度 應 skip
    idx_env = msg.find("整體環境")
    idx_put = msg.find("Sell PUT 機會檢視")
    idx_leaps = msg.find("LEAPS 進場檢視")
    idx_events = msg.find("今日事件")
    assert idx_env != -1 and idx_put != -1 and idx_leaps != -1 and idx_events != -1
    assert idx_env < idx_put < idx_leaps < idx_events
    # 持倉空 → 兩段 skip
    assert "Sell CALL 機會檢視" not in msg
    assert "部位健康度" not in msg
