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
# 用戶 L2 stub no_naked_call
# ============================
def test_lock2_naked_call_stub_passes_when_context_none():
    """Batch 7 stub:context=None → pass(視同 covered)"""
    ok, reason = veto_checker.check_lock_no_naked_call("AAPL", context=None)
    assert ok is True
    assert "stub" in reason.lower()


def test_lock2_naked_call_vetoes_when_uncovered():
    """context={covered_by: None} → veto"""
    ok, reason = veto_checker.check_lock_no_naked_call("AAPL", context={"covered_by": None})
    assert ok is False
    assert "naked" in reason.lower()


def test_lock2_naked_call_passes_when_covered_by_leaps():
    ok, _ = veto_checker.check_lock_no_naked_call("AAPL", context={"covered_by": "LEAPS"})
    assert ok is True


def test_lock2_naked_call_passes_when_covered_by_shares():
    ok, _ = veto_checker.check_lock_no_naked_call("AAPL", context={"covered_by": "shares"})
    assert ok is True


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
# 用戶 L5 stub hedge_dte<45
# ============================
def test_lock5_no_new_short_during_hedge_dte():
    """hedge_dte=30 → veto"""
    ok, reason = veto_checker.check_lock_hedge_dte("sell_call", context={"hedge_dte_days": 30})
    assert ok is False
    assert "hedge" in reason.lower() or "45" in reason, f"got {reason}"


def test_lock5_hedge_dte_stub_passes_when_context_none():
    """Batch 7 stub:context=None → pass"""
    ok, reason = veto_checker.check_lock_hedge_dte("sell_call", context=None)
    assert ok is True
    assert "stub" in reason.lower()


def test_lock5_hedge_dte_passes_when_above_45():
    ok, _ = veto_checker.check_lock_hedge_dte("sell_put", context={"hedge_dte_days": 60})
    assert ok is True


# ============================
# 用戶 L6 stub drawdown
# ============================
def test_lock6_no_new_leaps_during_drawdown_20():
    """drawdown=-22% → veto"""
    ok, reason = veto_checker.check_lock_drawdown("leaps_entry", context={"drawdown_pct": -0.22})
    assert ok is False
    assert "drawdown" in reason.lower() or "20" in reason, f"got {reason}"


def test_lock6_drawdown_stub_passes_when_context_none():
    """Batch 7 stub:context=None → pass"""
    ok, reason = veto_checker.check_lock_drawdown("leaps_entry", context=None)
    assert ok is True
    assert "stub" in reason.lower()


def test_lock6_drawdown_passes_when_above_20pct():
    """drawdown=-10% → pass(尚未達 -20%)"""
    ok, _ = veto_checker.check_lock_drawdown("leaps_entry", context={"drawdown_pct": -0.10})
    assert ok is True


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
    """乾淨 NVDA LEAPS:無財報、VIX 正常、DTE 540、非 2x ETF、無 context → 全 pass"""
    with patch("src.data.earnings_calendar.is_earnings_within_days", return_value=False), \
         patch("src.data.vix_structure.is_vix_consecutive_above", return_value=False):
        fails = veto_checker.check_all_hard_rules("leaps_entry", "NVDA", dte_days=540, ivr=50)
    reasons = [r for ok, r in fails if not ok]
    assert reasons == [], f"unexpected vetoes: {reasons}"
