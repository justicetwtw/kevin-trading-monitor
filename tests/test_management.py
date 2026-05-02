"""Batch 8 — management/ 5 模組 unit tests。

涵蓋:
- 三 mode get_account_snapshot 行為
- 冷啟動(positions.json 不存在)安全
- LEAPS 觸發點 +50/+100/-30/-40/DTE_low
- 帳戶回撤 -10/-20/-30 三級
- 純讀介面冷啟動回 None
- mode_1 警告 + flag 防重複
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest


# ============================
# Fixtures
# ============================

@pytest.fixture
def isolated_data_store(tmp_path, monkeypatch):
    """重導 DATA_STORE_DIR 到 tmp_path,確保測試 hermetic。"""
    fake_store = tmp_path / "data_store"
    fake_store.mkdir()

    # 重導所有引用 DATA_STORE_DIR 的模組
    monkeypatch.setattr("src.storage.state_manager.DATA_STORE_DIR", fake_store)
    monkeypatch.setattr("src.management.current_positions.DATA_STORE_DIR", fake_store)
    return fake_store


@pytest.fixture
def write_positions(isolated_data_store):
    def _write(positions: dict):
        (isolated_data_store / "positions.json").write_text(
            json.dumps(positions), encoding="utf-8"
        )
    return _write


# ============================
# 三 mode 冷啟動
# ============================

def test_mode_3_returns_empty_snapshot(isolated_data_store, monkeypatch):
    monkeypatch.setattr("src.management.current_positions.POSITION_MODE", "mode_3")
    from src.management import current_positions
    snap = current_positions.get_account_snapshot()
    assert snap["mode"] == "mode_3"
    assert snap["stocks"] == []
    assert snap["options"] == []
    assert snap["total_estimated_value"] is None
    assert snap["n_long_options"] == 0
    assert snap["n_short_options"] == 0
    assert "snapshot_at" in snap


def test_mode_2_cold_start_no_file(isolated_data_store, monkeypatch):
    """mode_2 + positions.json 不存在 → 空 snapshot,不 raise。"""
    monkeypatch.setattr("src.management.current_positions.POSITION_MODE", "mode_2")
    from src.management import current_positions
    snap = current_positions.get_account_snapshot()
    assert snap["mode"] == "mode_2"
    assert snap["stocks"] == []
    assert snap["options"] == []
    assert snap["total_estimated_value"] == 0.0
    assert snap["n_long_options"] == 0


def test_mode_1_cold_start_warns_and_writes_flag(isolated_data_store, monkeypatch):
    """mode_1 + 部位空 → 寫 flag,且第二次呼叫不重複警告。"""
    monkeypatch.setattr("src.management.current_positions.POSITION_MODE", "mode_1")
    flag = isolated_data_store / "mode1_warned.flag"
    assert not flag.exists()

    with patch("src.alerts.telegram_bot.send_telegram") as mock_tg:
        from src.management import current_positions
        snap1 = current_positions.get_account_snapshot()
        assert flag.exists(), "mode_1 第一次冷啟動必須寫 flag"
        assert mock_tg.call_count == 1, "mode_1 第一次必須推 Telegram 一次"

        snap2 = current_positions.get_account_snapshot()
        assert mock_tg.call_count == 1, "flag 已存在 → 不重複推"
    assert snap1["mode"] == "mode_1"
    assert snap2["mode"] == "mode_1"


def test_mode_1_with_real_positions_no_warning(isolated_data_store, monkeypatch, write_positions):
    """mode_1 + positions.json 有真實部位 → 不警告,不寫 flag。"""
    monkeypatch.setattr("src.management.current_positions.POSITION_MODE", "mode_1")
    write_positions({"stocks": [{"symbol": "NVDA", "shares": 100}], "options": []})
    flag = isolated_data_store / "mode1_warned.flag"

    with patch("src.alerts.telegram_bot.send_telegram") as mock_tg, \
         patch("src.management.current_positions._estimate_stock_value", return_value=15000.0):
        from src.management import current_positions
        current_positions.get_account_snapshot()
    assert not flag.exists(), "有真實部位不該寫 mode_1 flag"
    assert mock_tg.call_count == 0


def test_example_positions_treated_as_empty(isolated_data_store, monkeypatch, write_positions):
    """_example: True 的項目視同範本,不算真實部位。"""
    monkeypatch.setattr("src.management.current_positions.POSITION_MODE", "mode_2")
    write_positions({
        "stocks": [{"symbol": "EXAMPLE", "shares": 100, "_example": True}],
        "options": [{"symbol": "EXAMPLE", "type": "long_call", "_example": True}],
    })
    from src.management import current_positions
    snap = current_positions.get_account_snapshot()
    assert snap["n_long_options"] == 0
    assert current_positions.get_holdings_symbols() == []


# ============================
# get_long/short/holdings 過濾
# ============================

def test_get_long_options_filters(isolated_data_store, monkeypatch, write_positions):
    monkeypatch.setattr("src.management.current_positions.POSITION_MODE", "mode_2")
    write_positions({
        "stocks": [],
        "options": [
            {"symbol": "NVDA", "type": "long_call", "strike": 100, "expiry": "2027-01-15"},
            {"symbol": "QQQ", "type": "long_put", "strike": 400, "expiry": "2026-08-15"},
            {"symbol": "MSFT", "type": "short_call", "strike": 500, "expiry": "2026-06-19"},
        ],
    })
    from src.management import current_positions
    longs = current_positions.get_long_options()
    shorts = current_positions.get_short_options()
    assert len(longs) == 2
    assert len(shorts) == 1
    assert {l["type"] for l in longs} == {"long_call", "long_put"}


def test_mode_3_getters_return_empty(isolated_data_store, monkeypatch, write_positions):
    """mode_3 即使有 positions.json 也不讀。"""
    monkeypatch.setattr("src.management.current_positions.POSITION_MODE", "mode_3")
    write_positions({
        "stocks": [{"symbol": "NVDA", "shares": 100}],
        "options": [{"symbol": "NVDA", "type": "long_call", "strike": 100, "expiry": "2027-01-15"}],
    })
    from src.management import current_positions
    assert current_positions.get_long_options() == []
    assert current_positions.get_short_options() == []
    assert current_positions.get_holdings_symbols() == []


# ============================
# LEAPS 觸發點
# ============================

def _fake_pnl(pct: float, dte: int = 500) -> dict:
    return {"option_id": "X", "underlying": 150.0, "current_price_per_contract": 0,
            "cost_per_contract": 100, "pnl_pct": pct, "dte": dte}


def test_leaps_trigger_plus_100():
    from src.management import leaps_pnl_tracker
    with patch.object(leaps_pnl_tracker, "get_long_options",
                      return_value=[{"id": "X", "symbol": "NVDA", "type": "long_call",
                                     "strike": 100, "expiry": "2027-01-15",
                                     "cost_per_contract": 100}]), \
         patch.object(leaps_pnl_tracker, "calc_option_pnl", return_value=_fake_pnl(1.0, 500)):
        out = leaps_pnl_tracker.scan_all_leaps()
    levels = [t["level"] for t in out]
    assert "+100" in levels


def test_leaps_trigger_plus_50():
    from src.management import leaps_pnl_tracker
    with patch.object(leaps_pnl_tracker, "get_long_options",
                      return_value=[{"id": "X", "symbol": "NVDA", "type": "long_call",
                                     "strike": 100, "expiry": "2027-01-15",
                                     "cost_per_contract": 100}]), \
         patch.object(leaps_pnl_tracker, "calc_option_pnl", return_value=_fake_pnl(0.6, 500)):
        out = leaps_pnl_tracker.scan_all_leaps()
    levels = [t["level"] for t in out]
    assert "+50" in levels


def test_leaps_trigger_minus_30():
    from src.management import leaps_pnl_tracker
    with patch.object(leaps_pnl_tracker, "get_long_options",
                      return_value=[{"id": "X", "symbol": "NVDA", "type": "long_call",
                                     "strike": 100, "expiry": "2027-01-15",
                                     "cost_per_contract": 100}]), \
         patch.object(leaps_pnl_tracker, "calc_option_pnl", return_value=_fake_pnl(-0.32, 500)):
        out = leaps_pnl_tracker.scan_all_leaps()
    levels = [t["level"] for t in out]
    assert "-30" in levels


def test_leaps_trigger_minus_40():
    from src.management import leaps_pnl_tracker
    with patch.object(leaps_pnl_tracker, "get_long_options",
                      return_value=[{"id": "X", "symbol": "NVDA", "type": "long_call",
                                     "strike": 100, "expiry": "2027-01-15",
                                     "cost_per_contract": 100}]), \
         patch.object(leaps_pnl_tracker, "calc_option_pnl", return_value=_fake_pnl(-0.45, 500)):
        out = leaps_pnl_tracker.scan_all_leaps()
    levels = [t["level"] for t in out]
    assert "-40" in levels


def test_leaps_trigger_dte_low():
    from src.management import leaps_pnl_tracker
    with patch.object(leaps_pnl_tracker, "get_long_options",
                      return_value=[{"id": "X", "symbol": "NVDA", "type": "long_call",
                                     "strike": 100, "expiry": "2026-06-15",
                                     "cost_per_contract": 100}]), \
         patch.object(leaps_pnl_tracker, "calc_option_pnl", return_value=_fake_pnl(0.05, 200)):
        out = leaps_pnl_tracker.scan_all_leaps()
    levels = [t["level"] for t in out]
    assert "DTE_low" in levels


def test_leaps_cold_start_empty():
    """無部位 → []。"""
    from src.management import leaps_pnl_tracker
    with patch.object(leaps_pnl_tracker, "get_long_options", return_value=[]):
        assert leaps_pnl_tracker.scan_all_leaps() == []


def test_leaps_alias():
    """check_leaps_triggers 是 scan_all_leaps 的 alias。"""
    from src.management import leaps_pnl_tracker
    assert leaps_pnl_tracker.check_leaps_triggers is leaps_pnl_tracker.scan_all_leaps


# ============================
# Short Delta
# ============================

def test_short_delta_warns_above_threshold():
    from src.management import short_delta_monitor
    with patch.object(short_delta_monitor, "get_short_options",
                      return_value=[{"id": "S1", "symbol": "NVDA", "type": "short_call",
                                     "strike": 100, "expiry": "2027-01-15"}]), \
         patch.object(short_delta_monitor, "get_latest_price", return_value=150.0), \
         patch.object(short_delta_monitor, "get_atm_iv", return_value=0.30), \
         patch.object(short_delta_monitor, "calc_delta", return_value=0.50):
        alerts = short_delta_monitor.scan_all_shorts()
    assert len(alerts) == 1
    assert alerts[0]["symbol"] == "NVDA"


def test_short_delta_quiet_below_threshold():
    from src.management import short_delta_monitor
    with patch.object(short_delta_monitor, "get_short_options",
                      return_value=[{"id": "S1", "symbol": "NVDA", "type": "short_call",
                                     "strike": 200, "expiry": "2027-01-15"}]), \
         patch.object(short_delta_monitor, "get_latest_price", return_value=150.0), \
         patch.object(short_delta_monitor, "get_atm_iv", return_value=0.30), \
         patch.object(short_delta_monitor, "calc_delta", return_value=0.20):
        alerts = short_delta_monitor.scan_all_shorts()
    assert alerts == []


def test_short_delta_cold_start():
    from src.management import short_delta_monitor
    with patch.object(short_delta_monitor, "get_short_options", return_value=[]):
        assert short_delta_monitor.scan_all_shorts() == []


# ============================
# Hedge DTE
# ============================

def test_hedge_dte_alerts_below_45():
    from src.management import hedge_dte_tracker
    from datetime import datetime, timezone, timedelta
    expiry = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")
    with patch.object(hedge_dte_tracker, "get_long_options",
                      return_value=[{"id": "H1", "symbol": "QQQ", "type": "long_call",
                                     "strike": 400, "expiry": expiry}]):
        alerts = hedge_dte_tracker.scan_all_hedges()
    assert len(alerts) == 1
    assert alerts[0]["dte"] < 45


def test_hedge_dte_quiet_above_45():
    from src.management import hedge_dte_tracker
    from datetime import datetime, timezone, timedelta
    expiry = (datetime.now(timezone.utc) + timedelta(days=180)).strftime("%Y-%m-%d")
    with patch.object(hedge_dte_tracker, "get_long_options",
                      return_value=[{"id": "H1", "symbol": "QQQ", "type": "long_call",
                                     "strike": 400, "expiry": expiry}]):
        alerts = hedge_dte_tracker.scan_all_hedges()
    assert alerts == []


def test_hedge_dte_skips_non_hedge():
    """NVDA long_call 不是對沖 → 跳過。"""
    from src.management import hedge_dte_tracker
    from datetime import datetime, timezone, timedelta
    expiry = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")
    with patch.object(hedge_dte_tracker, "get_long_options",
                      return_value=[{"id": "L1", "symbol": "NVDA", "type": "long_call",
                                     "strike": 100, "expiry": expiry}]):
        assert hedge_dte_tracker.scan_all_hedges() == []


def test_get_min_hedge_dte_cold_start():
    """無 hedge → None。"""
    from src.management import hedge_dte_tracker
    with patch.object(hedge_dte_tracker, "get_long_options", return_value=[]):
        assert hedge_dte_tracker.get_min_hedge_dte() is None


def test_get_min_hedge_dte_returns_min():
    from src.management import hedge_dte_tracker
    from datetime import datetime, timezone, timedelta
    e30 = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")
    e90 = (datetime.now(timezone.utc) + timedelta(days=90)).strftime("%Y-%m-%d")
    with patch.object(hedge_dte_tracker, "get_long_options",
                      return_value=[
                          {"id": "H1", "symbol": "QQQ", "type": "long_call", "expiry": e90},
                          {"id": "H2", "symbol": "SPY", "type": "long_put", "expiry": e30},
                      ]):
        m = hedge_dte_tracker.get_min_hedge_dte()
    assert m is not None
    assert 28 <= m <= 31


# ============================
# Account drawdown
# ============================

def test_drawdown_level_1(isolated_data_store):
    from src.management import account_drawdown
    account_drawdown.update_account_value(100_000)
    h = account_drawdown.update_account_value(89_000)  # -11%
    assert h["alert_level"] == "level_1"


def test_drawdown_level_2(isolated_data_store):
    from src.management import account_drawdown
    account_drawdown.update_account_value(100_000)
    h = account_drawdown.update_account_value(78_000)  # -22%
    assert h["alert_level"] == "level_2"


def test_drawdown_level_3(isolated_data_store):
    from src.management import account_drawdown
    account_drawdown.update_account_value(100_000)
    h = account_drawdown.update_account_value(65_000)  # -35%
    assert h["alert_level"] == "level_3"


def test_drawdown_normal(isolated_data_store):
    from src.management import account_drawdown
    account_drawdown.update_account_value(100_000)
    h = account_drawdown.update_account_value(95_000)  # -5%
    assert h["alert_level"] == "normal"
    assert h["action"] is None


def test_drawdown_peak_updates(isolated_data_store):
    from src.management import account_drawdown
    account_drawdown.update_account_value(100_000)
    h = account_drawdown.update_account_value(120_000)
    assert h["peak"] == 120_000


def test_get_current_drawdown_cold_start(isolated_data_store):
    """無歷史 → drawdown_pct=None,不崩。"""
    from src.management import account_drawdown
    snap = account_drawdown.get_current_drawdown()
    assert snap["drawdown_pct"] is None
    assert snap["alert_level"] == "normal"


def test_get_current_drawdown_after_update(isolated_data_store):
    from src.management import account_drawdown
    account_drawdown.update_account_value(100_000)
    account_drawdown.update_account_value(78_000)
    snap = account_drawdown.get_current_drawdown()
    assert snap["drawdown_pct"] is not None
    assert abs(snap["drawdown_pct"] - (-0.22)) < 0.001
    assert snap["alert_level"] == "level_2"


# ============================
# Aliases
# ============================

def test_aliases_match_main_names():
    from src.management import leaps_pnl_tracker, short_delta_monitor, hedge_dte_tracker
    assert leaps_pnl_tracker.check_leaps_triggers is leaps_pnl_tracker.scan_all_leaps
    assert short_delta_monitor.check_short_deltas is short_delta_monitor.scan_all_shorts
    assert hedge_dte_tracker.check_hedge_dte is hedge_dte_tracker.scan_all_hedges
