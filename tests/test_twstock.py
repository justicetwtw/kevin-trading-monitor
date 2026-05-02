"""Batch 9 — twstock/ 三檔 unit tests(test-first)。

涵蓋:
- 核心三級觸發(A/B/C)各觸發 / 不觸發
- cooldown:14 天內降 white、>14 天放行
- mark_deployed 寫檔正確
- 主動 ETF Tier 1/2/3
- 冷啟動 no_data 不崩
- VIX None 時 C 級不誤觸發
"""

import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pandas as pd
import pytest


# ============================
# Fixtures
# ============================

@pytest.fixture
def isolated_data_store(tmp_path, monkeypatch):
    fake = tmp_path / "data_store"
    fake.mkdir()
    monkeypatch.setattr("src.storage.state_manager.DATA_STORE_DIR", fake)
    return fake


def _make_history(prices: list, end_date=None):
    """構造 100 日的價格序列(yfinance-like 結構)。最後 N 筆用 prices 覆蓋。"""
    end = end_date or datetime(2026, 5, 1)
    n = max(len(prices), 100)
    dates = pd.date_range(end=end, periods=n, freq="B")
    base = [100.0] * (n - len(prices)) + list(prices)
    df = pd.DataFrame({
        "Open": base, "High": [p * 1.01 for p in base],
        "Low": [p * 0.99 for p in base], "Close": base,
        "Volume": [1_000_000] * n,
    }, index=dates)
    return df


def _make_descending_history(start: float, end: float, n: int = 260):
    """從 start 線性下跌到 end,長度 n(用於模擬從 52W 高跌下來)。"""
    dates = pd.date_range(end=datetime(2026, 5, 1), periods=n, freq="B")
    closes = [start - (start - end) * i / (n - 1) for i in range(n)]
    df = pd.DataFrame({
        "Open": closes, "High": [c * 1.005 for c in closes],
        "Low": [c * 0.995 for c in closes], "Close": closes,
        "Volume": [1_000_000] * n,
    }, index=dates)
    return df


# ============================
# 核心三級觸發
# ============================

def test_core_tier_a_triggers(isolated_data_store):
    """52W 高 100 → 現價 89 (-11%) + 週 RSI 35 → A 級觸發"""
    from src.twstock import twstock_signals
    df = _make_descending_history(100.0, 89.0)
    with patch.object(twstock_signals, "fetch_tw_history", return_value=df), \
         patch.object(twstock_signals, "get_tw_52w_metrics",
                      return_value={"high": 100.0, "low": 80.0, "current": 89.0,
                                    "pct_from_high": -0.11, "pct_from_low": 0.11}), \
         patch.object(twstock_signals, "get_rsi_latest", return_value=35.0), \
         patch.object(twstock_signals, "fetch_vix_term_structure",
                      return_value={"vix": 18.0}):
        sig = twstock_signals.evaluate_00631l_signal()
    assert sig["tier"] == "A", f"expected A, got {sig}"
    assert sig["alert_level"] == "green"
    assert sig["deploy_pct"] == 0.25
    assert sig["cooldown"] is False


def test_core_tier_a_not_triggered_above_drawdown(isolated_data_store):
    """52W 高 100 → 現價 95 (-5%) → 不觸發 A"""
    from src.twstock import twstock_signals
    df = _make_descending_history(100.0, 95.0)
    with patch.object(twstock_signals, "fetch_tw_history", return_value=df), \
         patch.object(twstock_signals, "get_tw_52w_metrics",
                      return_value={"high": 100.0, "low": 80.0, "current": 95.0,
                                    "pct_from_high": -0.05, "pct_from_low": 0.19}), \
         patch.object(twstock_signals, "get_rsi_latest", return_value=35.0), \
         patch.object(twstock_signals, "fetch_vix_term_structure",
                      return_value={"vix": 18.0}):
        sig = twstock_signals.evaluate_00631l_signal()
    assert sig["tier"] is None, f"expected None, got {sig}"


def test_core_tier_b_triggers(isolated_data_store):
    """-22% + 週 RSI 32 → B 級"""
    from src.twstock import twstock_signals
    df = _make_descending_history(100.0, 78.0)
    with patch.object(twstock_signals, "fetch_tw_history", return_value=df), \
         patch.object(twstock_signals, "get_tw_52w_metrics",
                      return_value={"high": 100.0, "low": 70.0, "current": 78.0,
                                    "pct_from_high": -0.22, "pct_from_low": 0.11}), \
         patch.object(twstock_signals, "get_rsi_latest", return_value=32.0), \
         patch.object(twstock_signals, "fetch_vix_term_structure",
                      return_value={"vix": 20.0}):
        sig = twstock_signals.evaluate_00631l_signal()
    assert sig["tier"] == "B"
    assert sig["deploy_pct"] == 0.35


def test_core_tier_b_not_triggered_high_rsi(isolated_data_store):
    """-22% 但週 RSI 50(>35)→ 不觸發 B,但 -22% < -10% 仍滿足 A 條件 → A?

    A 條件:pct -10% AND 週 RSI < 40。RSI 50 不過。
    所以三級全 fail → tier None
    """
    from src.twstock import twstock_signals
    df = _make_descending_history(100.0, 78.0)
    with patch.object(twstock_signals, "fetch_tw_history", return_value=df), \
         patch.object(twstock_signals, "get_tw_52w_metrics",
                      return_value={"high": 100.0, "low": 70.0, "current": 78.0,
                                    "pct_from_high": -0.22, "pct_from_low": 0.11}), \
         patch.object(twstock_signals, "get_rsi_latest", return_value=50.0), \
         patch.object(twstock_signals, "fetch_vix_term_structure",
                      return_value={"vix": 18.0}):
        sig = twstock_signals.evaluate_00631l_signal()
    assert sig["tier"] is None


def test_core_tier_c_triggers_with_vix(isolated_data_store):
    """-32% + 週 RSI 28 + VIX 38 → C 級"""
    from src.twstock import twstock_signals
    df = _make_descending_history(100.0, 68.0)
    with patch.object(twstock_signals, "fetch_tw_history", return_value=df), \
         patch.object(twstock_signals, "get_tw_52w_metrics",
                      return_value={"high": 100.0, "low": 60.0, "current": 68.0,
                                    "pct_from_high": -0.32, "pct_from_low": 0.13}), \
         patch.object(twstock_signals, "get_rsi_latest", return_value=28.0), \
         patch.object(twstock_signals, "fetch_vix_term_structure",
                      return_value={"vix": 38.0}):
        sig = twstock_signals.evaluate_00631l_signal()
    assert sig["tier"] == "C"
    assert sig["deploy_pct"] == 0.40


def test_core_tier_c_not_triggered_when_vix_none(isolated_data_store):
    """-32% + 週 RSI 28 但 VIX None → 不觸發 C(VIX 是 hard 條件)"""
    from src.twstock import twstock_signals
    df = _make_descending_history(100.0, 68.0)
    with patch.object(twstock_signals, "fetch_tw_history", return_value=df), \
         patch.object(twstock_signals, "get_tw_52w_metrics",
                      return_value={"high": 100.0, "low": 60.0, "current": 68.0,
                                    "pct_from_high": -0.32, "pct_from_low": 0.13}), \
         patch.object(twstock_signals, "get_rsi_latest", return_value=28.0), \
         patch.object(twstock_signals, "fetch_vix_term_structure",
                      return_value={"vix": None}):
        sig = twstock_signals.evaluate_00631l_signal()
    # -32% & RSI 28 仍可滿足 B 條件(-20% & RSI<35)
    assert sig["tier"] == "B", f"VIX None 應降級為 B,got {sig}"


def test_2330_tier_a_triggers(isolated_data_store):
    """2330 同核心級別:52W 高 -11% + 週 RSI 38 → A"""
    from src.twstock import twstock_signals
    df = _make_descending_history(800.0, 712.0)
    with patch.object(twstock_signals, "fetch_tw_history", return_value=df), \
         patch.object(twstock_signals, "get_tw_52w_metrics",
                      return_value={"high": 800.0, "low": 600.0, "current": 712.0,
                                    "pct_from_high": -0.11, "pct_from_low": 0.187}), \
         patch.object(twstock_signals, "get_rsi_latest", return_value=38.0), \
         patch.object(twstock_signals, "fetch_vix_term_structure",
                      return_value={"vix": 18.0}):
        sig = twstock_signals.evaluate_2330_signal()
    assert sig["tier"] == "A"
    assert sig["symbol"] == "2330.TW"


# ============================
# Cooldown
# ============================

def test_cooldown_active_within_14d(isolated_data_store):
    """剛 mark_deployed → cooldown=True,alert_level 降 white"""
    from src.twstock import twstock_signals
    twstock_signals.mark_deployed("00631L.TW", "A")

    df = _make_descending_history(100.0, 89.0)
    with patch.object(twstock_signals, "fetch_tw_history", return_value=df), \
         patch.object(twstock_signals, "get_tw_52w_metrics",
                      return_value={"high": 100.0, "low": 80.0, "current": 89.0,
                                    "pct_from_high": -0.11, "pct_from_low": 0.11}), \
         patch.object(twstock_signals, "get_rsi_latest", return_value=35.0), \
         patch.object(twstock_signals, "fetch_vix_term_structure",
                      return_value={"vix": 18.0}):
        sig = twstock_signals.evaluate_00631l_signal()
    assert sig["tier"] == "A", "tier 仍應計算"
    assert sig["cooldown"] is True
    assert sig["alert_level"] == "white", "cooldown 期降 white"


def test_cooldown_released_after_14d(isolated_data_store):
    """假裝 last_deploy_date 為 20 天前 → cooldown=False"""
    from src.twstock import twstock_signals
    fake_old = (datetime.now() - timedelta(days=20)).date().isoformat()
    log_path = isolated_data_store / "twstock_deployment_log.json"
    log_path.write_text(json.dumps({
        "00631L.TW": {"last_deploy_date": fake_old, "last_tier": "A"}
    }), encoding="utf-8")

    df = _make_descending_history(100.0, 89.0)
    with patch.object(twstock_signals, "fetch_tw_history", return_value=df), \
         patch.object(twstock_signals, "get_tw_52w_metrics",
                      return_value={"high": 100.0, "low": 80.0, "current": 89.0,
                                    "pct_from_high": -0.11, "pct_from_low": 0.11}), \
         patch.object(twstock_signals, "get_rsi_latest", return_value=35.0), \
         patch.object(twstock_signals, "fetch_vix_term_structure",
                      return_value={"vix": 18.0}):
        sig = twstock_signals.evaluate_00631l_signal()
    assert sig["tier"] == "A"
    assert sig["cooldown"] is False
    assert sig["alert_level"] == "green"


def test_mark_deployed_writes_correct_schema(isolated_data_store):
    from src.twstock import twstock_signals
    twstock_signals.mark_deployed("2330.TW", "B")
    log_path = isolated_data_store / "twstock_deployment_log.json"
    assert log_path.exists()
    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert "2330.TW" in data
    assert data["2330.TW"]["last_tier"] == "B"
    # last_deploy_date 必須是 YYYY-MM-DD 字串
    datetime.strptime(data["2330.TW"]["last_deploy_date"], "%Y-%m-%d")


def test_get_cooldown_status_no_record(isolated_data_store):
    from src.twstock import twstock_signals
    status = twstock_signals.get_cooldown_status("00631L.TW")
    assert status["in_cooldown"] is False
    assert status["days_remaining"] == 0


def test_get_cooldown_status_within_window(isolated_data_store):
    from src.twstock import twstock_signals
    twstock_signals.mark_deployed("00631L.TW", "A")
    status = twstock_signals.get_cooldown_status("00631L.TW")
    assert status["in_cooldown"] is True
    assert 0 <= status["days_remaining"] <= 14


# ============================
# 冷啟動 / 錯誤路徑
# ============================

def test_evaluate_no_data_returns_safe_dict(isolated_data_store):
    """fetch 回空 df → no_data,不崩"""
    from src.twstock import twstock_signals
    with patch.object(twstock_signals, "fetch_tw_history", return_value=pd.DataFrame()), \
         patch.object(twstock_signals, "get_tw_52w_metrics",
                      return_value={"high": None, "low": None, "current": None,
                                    "pct_from_high": None, "pct_from_low": None}):
        sig = twstock_signals.evaluate_00631l_signal()
    assert sig["tier"] is None
    assert sig.get("action") == "no_data" or sig.get("signal") == "no_data"
    assert sig["alert_level"] == "none"


def test_scan_twstock_core_returns_two_dicts(isolated_data_store):
    from src.twstock import twstock_signals
    with patch.object(twstock_signals, "fetch_tw_history", return_value=pd.DataFrame()), \
         patch.object(twstock_signals, "get_tw_52w_metrics",
                      return_value={"high": None, "low": None, "current": None,
                                    "pct_from_high": None, "pct_from_low": None}):
        out = twstock_signals.scan_twstock_core()
    assert len(out) == 2
    assert {s["symbol"] for s in out} == {"00631L.TW", "2330.TW"}


# ============================
# 主動 ETF 三級
# ============================

def test_active_etf_tier1_single_etf_1pct(isolated_data_store):
    """單一 ETF 加碼某股 1.5 pp → 🟡 Tier 1"""
    from src.twstock import active_etf_signals
    fake_agg = {
        "2330": {
            "increased_etfs": [
                {"etf": "00981A.TW", "etf_name": "X", "diff_pct": 1.5},
            ],
            "decreased_etfs": [],
        }
    }
    with patch.object(active_etf_signals, "aggregate_cross_etf_signals",
                      side_effect=lambda lookback_days=7: fake_agg if lookback_days == 7 else {}):
        sig = active_etf_signals.evaluate_active_etf("2330")
    assert sig["tier"] == 1
    assert sig["alert_level"] == "yellow"


def test_active_etf_tier2_three_etfs_7d(isolated_data_store):
    """7 天內 3 檔 ETF 加碼同股 → 🟠 Tier 2"""
    from src.twstock import active_etf_signals
    fake_agg_7d = {
        "2454": {
            "increased_etfs": [
                {"etf": "00981A.TW", "etf_name": "X", "diff_pct": 1.2},
                {"etf": "00982A.TW", "etf_name": "Y", "diff_pct": 1.1},
                {"etf": "00992A.TW", "etf_name": "Z", "diff_pct": 1.5},
            ],
            "decreased_etfs": [],
        }
    }
    with patch.object(active_etf_signals, "aggregate_cross_etf_signals",
                      side_effect=lambda lookback_days=7: fake_agg_7d if lookback_days == 7 else {}):
        sig = active_etf_signals.evaluate_active_etf("2454")
    assert sig["tier"] == 2
    assert sig["alert_level"] == "orange"


def test_active_etf_tier3_five_etfs_30d(isolated_data_store):
    """30 天 ≥5 檔共識 → 🔴 Tier 3"""
    from src.twstock import active_etf_signals
    fake_agg_7d = {}
    fake_agg_30d = {
        "3008": {
            "increased_etfs": [
                {"etf": f"0098{i}A.TW", "etf_name": f"E{i}", "diff_pct": 1.0}
                for i in range(5)
            ],
            "decreased_etfs": [],
        }
    }

    def side(lookback_days=7):
        return fake_agg_7d if lookback_days == 7 else fake_agg_30d

    with patch.object(active_etf_signals, "aggregate_cross_etf_signals", side_effect=side):
        sig = active_etf_signals.evaluate_active_etf("3008")
    assert sig["tier"] == 3
    assert sig["alert_level"] == "red"


def test_active_etf_no_data(isolated_data_store):
    """資料源完全空 → tier=None / no_data,不崩"""
    from src.twstock import active_etf_signals
    with patch.object(active_etf_signals, "aggregate_cross_etf_signals", return_value={}):
        sig = active_etf_signals.evaluate_active_etf("2330")
    assert sig["tier"] is None
    assert sig["alert_level"] == "none"


def test_scan_all_active_etfs_iterates_universe(isolated_data_store):
    """掃 universe,即使全 no_data 也回 list 不崩"""
    from src.twstock import active_etf_signals
    with patch.object(active_etf_signals, "aggregate_cross_etf_signals", return_value={}):
        out = active_etf_signals.scan_all_active_etfs()
    assert isinstance(out, list)
    assert len(out) >= 1


def test_active_etf_tier1_below_threshold_not_triggered(isolated_data_store):
    """diff_pct 0.7 < 1.0 pp → 不觸發"""
    from src.twstock import active_etf_signals
    fake_agg = {
        "2330": {
            "increased_etfs": [{"etf": "00981A.TW", "etf_name": "X", "diff_pct": 0.7}],
            "decreased_etfs": [],
        }
    }
    with patch.object(active_etf_signals, "aggregate_cross_etf_signals",
                      side_effect=lambda lookback_days=7: fake_agg if lookback_days == 7 else {}):
        sig = active_etf_signals.evaluate_active_etf("2330")
    assert sig["tier"] is None


# ============================
# Alerts 格式化
# ============================

def test_format_filters_tier_none():
    from src.twstock.twstock_alerts import format_twstock_alert
    assert format_twstock_alert({"tier": None, "symbol": "2330"}) is None


def test_format_includes_emoji_and_action():
    from src.twstock.twstock_alerts import format_twstock_alert
    sig = {
        "symbol": "00631L.TW", "name": "元大台灣 50 正 2",
        "tier": "A", "action": "重壓加碼", "alert_level": "green",
        "price": 50.0, "rsi14_weekly": 35.0, "pct_from_52w_high": -0.11,
        "deploy_pct": 0.25, "cooldown": False,
    }
    msg = format_twstock_alert(sig)
    assert msg is not None
    assert "🟢" in msg
    assert "00631L.TW" in msg
    assert "A" in msg
    assert "25" in msg or "0.25" in msg


def test_collect_filters_no_data(isolated_data_store):
    from src.twstock import twstock_alerts
    with patch.object(twstock_alerts, "scan_twstock_core",
                      return_value=[{"symbol": "00631L.TW", "tier": None, "alert_level": "none"}]), \
         patch.object(twstock_alerts, "scan_all_active_etfs", return_value=[]):
        alerts = twstock_alerts.collect_twstock_alerts()
    assert alerts == []
