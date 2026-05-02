"""Batch 7 Step 1 — 學習鎖 unit tests(test-first)。

對應使用者 L1–L6 編號 + v4 真實 6 條(含使用者沒列的 DTE / IVR / VIX 連 3 天)。
所有外部 data 來源全部 patch,測試保持 hermetic。
"""

from unittest.mock import patch

from src.signals import veto_checker


# ============================
# 用戶 L1 / v4 tier_c_no_sell_put
# ============================
def test_lock1_tier_c_cant_sell_put():
    """PLTR 賣 PUT → veto"""
    with patch("src.signals.veto_checker.is_earnings_within_days", return_value=False):
        fails = veto_checker.check_all_hard_rules("sell_put", "PLTR")
    reasons = [r for ok, r in fails if not ok]
    assert any("tier_c" in r.lower() for r in reasons), f"expected tier_c veto, got {reasons}"


def test_lock1_tier_a_passes():
    """NVDA 賣 PUT(白名單)→ pass tier_c 鎖"""
    with patch("src.signals.veto_checker.is_earnings_within_days", return_value=False):
        fails = veto_checker.check_all_hard_rules("sell_put", "NVDA", ivr=50)
    reasons = [r for ok, r in fails if not ok]
    assert not any("tier_c" in r.lower() for r in reasons), f"unexpected tier_c: {reasons}"


# ============================
# 用戶 L2 — covered call(實邏輯,從 load_positions 讀)
# ============================
def test_lock2_naked_call_uncovered_vetoes(monkeypatch):
    """sell_call AAPL,positions 空 → veto"""
    monkeypatch.setattr(
        "src.signals.veto_checker.load_positions",
        lambda: {"stocks": [], "options": []},
    )
    ok, reason = veto_checker.check_lock_no_naked_call("sell_call", "AAPL")
    assert ok is False
    assert "naked" in reason.lower()


def test_lock2_passes_when_holding_shares(monkeypatch):
    monkeypatch.setattr(
        "src.signals.veto_checker.load_positions",
        lambda: {"stocks": [{"symbol": "AAPL", "shares": 100}], "options": []},
    )
    ok, _ = veto_checker.check_lock_no_naked_call("sell_call", "AAPL")
    assert ok is True


def test_lock2_passes_when_holding_long_call(monkeypatch):
    monkeypatch.setattr(
        "src.signals.veto_checker.load_positions",
        lambda: {
            "stocks": [],
            "options": [{"symbol": "AAPL", "type": "long_call", "strike": 200,
                         "expiry": "2027-01-15"}],
        },
    )
    ok, _ = veto_checker.check_lock_no_naked_call("sell_call", "AAPL")
    assert ok is True


def test_lock2_skips_for_non_sell_call(monkeypatch):
    """sell_put / leaps_entry → n/a"""
    monkeypatch.setattr(
        "src.signals.veto_checker.load_positions",
        lambda: {"stocks": [], "options": []},
    )
    ok, reason = veto_checker.check_lock_no_naked_call("sell_put", "AAPL")
    assert ok is True
    assert reason == "n/a"


def test_lock2_context_override_covered(monkeypatch):
    """context={covered_by:'LEAPS'} 顯式短路 → pass(不讀 positions)"""
    called = {"n": 0}

    def fail(*a, **k):
        called["n"] += 1
        raise AssertionError("load_positions should not be called")

    monkeypatch.setattr("src.signals.veto_checker.load_positions", fail)
    ok, reason = veto_checker.check_lock_no_naked_call(
        "sell_call", "AAPL", context={"covered_by": "LEAPS"}
    )
    assert ok is True
    assert "leaps" in reason.lower()
    assert called["n"] == 0


def test_lock2_disabled_via_hard_rules(monkeypatch):
    """require_covered_for_short_call=False → 整條 pass"""
    monkeypatch.setitem(
        veto_checker.HARD_RULES, "require_covered_for_short_call", False
    )
    ok, reason = veto_checker.check_lock_no_naked_call("sell_call", "AAPL")
    assert ok is True
    assert reason == "rule_disabled"


def test_lock2_ignores_example_positions(monkeypatch):
    """_example: True 不算真實部位 → 仍視為 naked"""
    monkeypatch.setattr(
        "src.signals.veto_checker.load_positions",
        lambda: {
            "stocks": [{"symbol": "AAPL", "shares": 100, "_example": True}],
            "options": [],
        },
    )
    ok, _ = veto_checker.check_lock_no_naked_call("sell_call", "AAPL")
    assert ok is False


# ============================
# 用戶 L3 / v4 2x ETF no LEAPS
# ============================
def test_lock3_no_2x_etf_leaps():
    """NVDL 買 LEAPS → veto"""
    with patch("src.signals.veto_checker.is_vix_consecutive_above", return_value=False):
        fails = veto_checker.check_all_hard_rules("leaps_entry", "NVDL", dte_days=540)
    reasons = [r for ok, r in fails if not ok]
    assert any("2x_etf" in r.lower() or "nvdl" in r.lower() for r in reasons), \
        f"expected 2x_etf veto, got {reasons}"


def test_lock3_regular_stock_leaps_passes():
    """NVDA 買 LEAPS(非 2x ETF)→ pass"""
    with patch("src.signals.veto_checker.is_vix_consecutive_above", return_value=False):
        fails = veto_checker.check_all_hard_rules("leaps_entry", "NVDA", dte_days=540)
    reasons = [r for ok, r in fails if not ok]
    assert not any("2x_etf" in r.lower() for r in reasons), f"unexpected 2x_etf: {reasons}"


# ============================
# 用戶 L4 / v4 earnings_blackout
# ============================
def test_lock4_no_short_within_7d_earnings():
    """earnings 7 天內賣 CALL → veto"""
    with patch("src.signals.veto_checker.is_earnings_within_days", return_value=True):
        fails = veto_checker.check_all_hard_rules("sell_call", "NVDA", ivr=50)
    reasons = [r for ok, r in fails if not ok]
    assert any("earnings" in r.lower() for r in reasons), f"expected earnings veto, got {reasons}"


def test_lock4_pass_when_no_earnings():
    """earnings 999 天後 → pass"""
    with patch("src.signals.veto_checker.is_earnings_within_days", return_value=False):
        fails = veto_checker.check_all_hard_rules("sell_call", "NVDA", ivr=50)
    reasons = [r for ok, r in fails if not ok]
    assert not any("earnings" in r.lower() for r in reasons), f"unexpected earnings: {reasons}"


# ============================
# 用戶 L5 — hedge_dte<45(實邏輯,從 get_min_hedge_dte 讀)
# ============================
def test_lock5_no_hedge_position_passes(monkeypatch):
    """無 hedge 部位 → pass(冷啟動安全)"""
    monkeypatch.setattr("src.signals.veto_checker.get_min_hedge_dte", lambda: None)
    ok, reason = veto_checker.check_lock_hedge_dte("sell_call")
    assert ok is True
    assert reason == "no_hedge_position"


def test_lock5_below_threshold_vetoes(monkeypatch):
    """hedge DTE 30 < 45 → veto"""
    monkeypatch.setattr("src.signals.veto_checker.get_min_hedge_dte", lambda: 30)
    ok, reason = veto_checker.check_lock_hedge_dte("sell_call")
    assert ok is False
    assert "lock5" in reason
    assert "30" in reason


def test_lock5_above_threshold_passes(monkeypatch):
    monkeypatch.setattr("src.signals.veto_checker.get_min_hedge_dte", lambda: 60)
    ok, _ = veto_checker.check_lock_hedge_dte("sell_put")
    assert ok is True


def test_lock5_skips_for_leaps_entry(monkeypatch):
    """leaps_entry → n/a(L5 只擋短倉)"""
    monkeypatch.setattr("src.signals.veto_checker.get_min_hedge_dte", lambda: 10)
    ok, reason = veto_checker.check_lock_hedge_dte("leaps_entry")
    assert ok is True
    assert reason == "n/a"


def test_lock5_context_override(monkeypatch):
    """context={hedge_dte_days:30} 短路,不讀 management"""
    called = {"n": 0}

    def fail():
        called["n"] += 1
        raise AssertionError("get_min_hedge_dte should not be called")

    monkeypatch.setattr("src.signals.veto_checker.get_min_hedge_dte", fail)
    ok, _ = veto_checker.check_lock_hedge_dte(
        "sell_call", context={"hedge_dte_days": 30}
    )
    assert ok is False
    assert called["n"] == 0


# ============================
# 用戶 L6 — drawdown(實邏輯,從 get_current_drawdown 讀)
# ============================
def test_lock6_no_account_history_passes(monkeypatch):
    """無 account 歷史 → pass(冷啟動安全)"""
    monkeypatch.setattr(
        "src.signals.veto_checker.get_current_drawdown",
        lambda: {"drawdown_pct": None, "alert_level": "normal"},
    )
    ok, reason = veto_checker.check_lock_drawdown("leaps_entry")
    assert ok is True
    assert reason == "no_account_value_history"


def test_lock6_at_or_below_threshold_vetoes(monkeypatch):
    """drawdown -22% → veto"""
    monkeypatch.setattr(
        "src.signals.veto_checker.get_current_drawdown",
        lambda: {"drawdown_pct": -0.22, "alert_level": "level_2"},
    )
    ok, reason = veto_checker.check_lock_drawdown("leaps_entry")
    assert ok is False
    assert "lock6" in reason


def test_lock6_above_threshold_passes(monkeypatch):
    """drawdown -10% → pass"""
    monkeypatch.setattr(
        "src.signals.veto_checker.get_current_drawdown",
        lambda: {"drawdown_pct": -0.10, "alert_level": "level_1"},
    )
    ok, _ = veto_checker.check_lock_drawdown("leaps_entry")
    assert ok is True


def test_lock6_skips_for_short_premium(monkeypatch):
    """sell_call / sell_put → n/a(L6 只擋新 LEAPS)"""
    monkeypatch.setattr(
        "src.signals.veto_checker.get_current_drawdown",
        lambda: {"drawdown_pct": -0.50, "alert_level": "level_3"},
    )
    ok, reason = veto_checker.check_lock_drawdown("sell_put")
    assert ok is True
    assert reason == "n/a"


def test_lock6_context_override(monkeypatch):
    """context={drawdown_pct:-0.22} 短路,不讀 management"""
    called = {"n": 0}

    def fail():
        called["n"] += 1
        raise AssertionError("get_current_drawdown should not be called")

    monkeypatch.setattr("src.signals.veto_checker.get_current_drawdown", fail)
    ok, _ = veto_checker.check_lock_drawdown(
        "leaps_entry", context={"drawdown_pct": -0.22}
    )
    assert ok is False
    assert called["n"] == 0


# ============================
# v4 reals 用戶沒列(防禦性測試)
# ============================
def test_v4_min_leaps_dte_below_365():
    """LEAPS DTE=200 → veto(v4 真實學習鎖,用戶清單沒列)"""
    with patch("src.signals.veto_checker.is_vix_consecutive_above", return_value=False):
        fails = veto_checker.check_all_hard_rules("leaps_entry", "AAPL", dte_days=200)
    reasons = [r for ok, r in fails if not ok]
    assert any("dte" in r.lower() and "365" in r for r in reasons), \
        f"expected DTE 365 veto, got {reasons}"


def test_v4_min_ivr_below_30_short_premium():
    """IVR=20 賣 CALL → veto"""
    with patch("src.signals.veto_checker.is_earnings_within_days", return_value=False):
        fails = veto_checker.check_all_hard_rules("sell_call", "NVDA", ivr=20)
    reasons = [r for ok, r in fails if not ok]
    assert any("ivr" in r.lower() and "30" in r for r in reasons), \
        f"expected IVR 30 veto, got {reasons}"


def test_v4_vix_consecutive_above_30_blocks_leaps():
    """VIX 連 3 天 >30 → 擋 LEAPS"""
    with patch("src.signals.veto_checker.is_vix_consecutive_above", return_value=True):
        fails = veto_checker.check_all_hard_rules("leaps_entry", "AAPL", dte_days=540)
    reasons = [r for ok, r in fails if not ok]
    assert any("vix" in r.lower() for r in reasons), f"expected VIX veto, got {reasons}"


# ============================
# 全鎖通過情境
# ============================
def test_all_locks_pass_for_clean_nvda_leaps():
    """乾淨 NVDA LEAPS:無財報、VIX 正常、DTE 540、非 2x ETF、無 hedge / drawdown → 全 pass"""
    with patch("src.signals.veto_checker.is_earnings_within_days", return_value=False), \
         patch("src.signals.veto_checker.is_vix_consecutive_above", return_value=False), \
         patch("src.signals.veto_checker.get_min_hedge_dte", return_value=None), \
         patch("src.signals.veto_checker.get_current_drawdown",
               return_value={"drawdown_pct": None, "alert_level": "normal"}), \
         patch("src.signals.veto_checker.load_positions",
               return_value={"stocks": [], "options": []}):
        fails = veto_checker.check_all_hard_rules("leaps_entry", "NVDA", dte_days=540, ivr=50)
    reasons = [r for ok, r in fails if not ok]
    assert reasons == [], f"unexpected vetoes: {reasons}"
