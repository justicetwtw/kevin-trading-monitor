"""Phase 2.5.5 + Sprint 2.5.9 — runner 層測試:
- dedup
- 6 種 BRIEF_TYPE 驗證
- silent push (us_eod / us_midday)
- dedup migration (tw_eod → tw_close)
- get_market_state (logging-only)
"""

import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
import pytz

from src.runners import run_market_brief as rmb


@pytest.fixture
def tmp_dedup(tmp_path, monkeypatch):
    p = tmp_path / "data_store" / "brief_sent_today.json"
    monkeypatch.setattr(rmb, "DEDUP_PATH", p)
    return p


# ------------------------------------------------------------
# dedup
# ------------------------------------------------------------

def test_dedup_first_call_returns_false(tmp_dedup):
    assert rmb.is_already_sent_today("us_eod") is False


def test_dedup_after_mark_returns_true(tmp_dedup):
    rmb.mark_sent("us_eod")
    assert rmb.is_already_sent_today("us_eod") is True


def test_dedup_isolates_by_brief_type(tmp_dedup):
    rmb.mark_sent("us_eod")
    assert rmb.is_already_sent_today("tw_close") is False
    assert rmb.is_already_sent_today("us_eod") is True


def test_dedup_corrupt_file_treated_as_empty(tmp_dedup):
    tmp_dedup.parent.mkdir(parents=True, exist_ok=True)
    tmp_dedup.write_text("{not json", encoding="utf-8")
    assert rmb.is_already_sent_today("us_eod") is False


def test_dedup_clears_records_older_than_7_days(tmp_dedup):
    today = datetime.now(rmb.TIMEZONE_USER).date()
    old_day = (today - timedelta(days=10)).strftime("%Y-%m-%d")
    tmp_dedup.parent.mkdir(parents=True, exist_ok=True)
    tmp_dedup.write_text(
        json.dumps({old_day: {"us_eod": True}}), encoding="utf-8"
    )
    rmb.mark_sent("tw_close")
    data = json.loads(tmp_dedup.read_text(encoding="utf-8"))
    assert old_day not in data
    assert today.strftime("%Y-%m-%d") in data


# ------------------------------------------------------------
# Sprint 2.5.9 — dedup migration tw_eod → tw_close
# ------------------------------------------------------------

def test_migrate_tw_eod_to_tw_close_pure():
    state = {
        "2026-05-04": {"us_eod": True, "tw_eod": True},
        "2026-05-05": {"us_eod": True},
    }
    out = rmb._migrate_dedup_keys(state)
    assert "tw_eod" not in out["2026-05-04"]
    assert out["2026-05-04"]["tw_close"] is True
    assert out["2026-05-04"]["us_eod"] is True
    # 2026-05-05 沒 tw_eod,不動
    assert "tw_eod" not in out["2026-05-05"]
    assert "tw_close" not in out["2026-05-05"]


def test_migrate_tw_eod_with_existing_tw_close_or_merges():
    """同一天既有 tw_eod=True 又有 tw_close=False → 應 OR 合併為 True。"""
    state = {"2026-05-04": {"tw_eod": True, "tw_close": False}}
    out = rmb._migrate_dedup_keys(state)
    assert "tw_eod" not in out["2026-05-04"]
    assert out["2026-05-04"]["tw_close"] is True


def test_load_dedup_applies_migration_on_disk(tmp_dedup):
    """讀檔時 tw_eod 自動 rename。"""
    tmp_dedup.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.now(rmb.TIMEZONE_USER).strftime("%Y-%m-%d")
    tmp_dedup.write_text(
        json.dumps({today: {"tw_eod": True}}), encoding="utf-8"
    )
    # is_already_sent_today("tw_close") 應為 True (因為被 migrate)
    assert rmb.is_already_sent_today("tw_close") is True
    # tw_eod key 不再存在
    assert rmb.is_already_sent_today("tw_eod") is False


# ------------------------------------------------------------
# Sprint 2.5.9 — silent push 判斷
# ------------------------------------------------------------

def test_silent_us_eod():
    assert rmb.is_silent("us_eod") is True


def test_silent_us_midday():
    assert rmb.is_silent("us_midday") is True


def test_not_silent_tw_open():
    assert rmb.is_silent("tw_open") is False


def test_not_silent_tw_close():
    assert rmb.is_silent("tw_close") is False


def test_not_silent_us_premarket():
    assert rmb.is_silent("us_premarket") is False


def test_not_silent_us_open():
    assert rmb.is_silent("us_open") is False


def test_silent_brief_types_set_size():
    assert rmb.SILENT_BRIEF_TYPES == {"us_eod", "us_midday"}


# ------------------------------------------------------------
# Sprint 2.5.9 — get_market_state (logging-only, no dispatch)
# ------------------------------------------------------------

def _fake_now_et(hour: int, minute: int = 0, dst: bool = True):
    et = pytz.timezone("America/New_York")
    base_date = "2026-05-04" if dst else "2026-01-15"
    naive = datetime.strptime(f"{base_date} {hour:02d}:{minute:02d}:00",
                              "%Y-%m-%d %H:%M:%S")
    return et.localize(naive)


def test_market_state_premarket():
    fake_now = _fake_now_et(9, 0)
    with patch.object(rmb, "datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        state = rmb.get_market_state()
    assert state["phase"] == "premarket"
    assert state["is_dst"] is True


def test_market_state_intraday():
    fake_now = _fake_now_et(13, 0)
    with patch.object(rmb, "datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        state = rmb.get_market_state()
    assert state["phase"] == "intraday"


def test_market_state_afterhours():
    fake_now = _fake_now_et(18, 0)
    with patch.object(rmb, "datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        state = rmb.get_market_state()
    assert state["phase"] == "afterhours"


def test_market_state_winter_no_dst():
    fake_now = _fake_now_et(10, 0, dst=False)
    with patch.object(rmb, "datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        state = rmb.get_market_state()
    assert state["is_dst"] is False


# ------------------------------------------------------------
# Sprint 2.5.9 — VALID_BRIEF_TYPES validation in main()
# ------------------------------------------------------------

def test_main_invalid_brief_type_returns_1(tmp_dedup, monkeypatch):
    monkeypatch.setenv("BRIEF_TYPE", "garbage")
    rc = rmb.main()
    assert rc == 1


def test_main_old_tw_eod_rejected(tmp_dedup, monkeypatch):
    """舊 tw_eod 不再合法。"""
    monkeypatch.setenv("BRIEF_TYPE", "tw_eod")
    rc = rmb.main()
    assert rc == 1


@pytest.mark.parametrize("brief_type", [
    "us_eod", "tw_open", "tw_close", "us_premarket", "us_open", "us_midday",
])
def test_main_accepts_all_six_types(tmp_dedup, monkeypatch, brief_type):
    monkeypatch.setenv("BRIEF_TYPE", brief_type)
    with patch("src.runners.run_market_brief.BriefGenerator") as mock_gen, \
         patch("src.runners.run_market_brief.send_telegram",
               return_value=True):
        mock_gen.return_value.generate.return_value = "<b>fake</b>"
        rc = rmb.main()
    assert rc == 0


# ------------------------------------------------------------
# main() 整合
# ------------------------------------------------------------

def test_main_skips_when_already_sent(tmp_dedup, monkeypatch):
    monkeypatch.setenv("BRIEF_TYPE", "us_eod")
    rmb.mark_sent("us_eod")
    with patch.object(rmb, "send_telegram") as mock_send:
        rc = rmb.main()
    assert rc == 0
    mock_send.assert_not_called()


def test_main_marks_after_successful_send(tmp_dedup, monkeypatch):
    monkeypatch.setenv("BRIEF_TYPE", "us_eod")
    with patch("src.runners.run_market_brief.BriefGenerator") as mock_gen, \
         patch("src.runners.run_market_brief.send_telegram",
               return_value=True) as mock_send:
        mock_gen.return_value.generate.return_value = "<b>fake</b>"
        rc = rmb.main()
    assert rc == 0
    mock_send.assert_called_once()
    assert rmb.is_already_sent_today("us_eod") is True


def test_main_does_not_mark_when_send_fails(tmp_dedup, monkeypatch):
    monkeypatch.setenv("BRIEF_TYPE", "us_eod")
    with patch("src.runners.run_market_brief.BriefGenerator") as mock_gen, \
         patch("src.runners.run_market_brief.send_telegram",
               return_value=False):
        mock_gen.return_value.generate.return_value = "<b>fake</b>"
        rc = rmb.main()
    assert rc == 1
    assert rmb.is_already_sent_today("us_eod") is False


# ------------------------------------------------------------
# Sprint 2.5.9 — main() 把 silent 旗標傳給 send_telegram
# ------------------------------------------------------------

@pytest.mark.parametrize("brief_type,expect_silent", [
    ("us_eod", True),
    ("us_midday", True),
    ("tw_open", False),
    ("tw_close", False),
    ("us_premarket", False),
    ("us_open", False),
])
def test_main_passes_silent_flag(
    tmp_dedup, monkeypatch, brief_type, expect_silent,
):
    monkeypatch.setenv("BRIEF_TYPE", brief_type)
    with patch("src.runners.run_market_brief.BriefGenerator") as mock_gen, \
         patch("src.runners.run_market_brief.send_telegram",
               return_value=True) as mock_send:
        mock_gen.return_value.generate.return_value = "<b>fake</b>"
        rmb.main()
    args, kwargs = mock_send.call_args
    assert kwargs.get("disable_notification") is expect_silent
