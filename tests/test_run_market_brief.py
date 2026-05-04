"""Phase 2.5.5 + 2.5.6 — runner 層測試:dedup、DST 偵測、actual_brief_type。"""

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
    assert rmb.is_already_sent_today("tw_eod") is False
    assert rmb.is_already_sent_today("us_eod") is True


def test_dedup_corrupt_file_treated_as_empty(tmp_dedup):
    tmp_dedup.parent.mkdir(parents=True, exist_ok=True)
    tmp_dedup.write_text("{not json", encoding="utf-8")
    assert rmb.is_already_sent_today("us_eod") is False


def test_dedup_clears_records_older_than_7_days(tmp_dedup):
    """7 天前紀錄會被 mark_sent 清掉。"""
    today = datetime.now(rmb.TIMEZONE_USER).date()
    old_day = (today - timedelta(days=10)).strftime("%Y-%m-%d")
    tmp_dedup.parent.mkdir(parents=True, exist_ok=True)
    tmp_dedup.write_text(
        json.dumps({old_day: {"us_eod": True}}), encoding="utf-8"
    )
    rmb.mark_sent("tw_eod")
    data = json.loads(tmp_dedup.read_text(encoding="utf-8"))
    assert old_day not in data
    assert today.strftime("%Y-%m-%d") in data


# ------------------------------------------------------------
# get_market_state phase 判斷(用 freezegun 風格的 patch)
# ------------------------------------------------------------

def _fake_now_et(hour: int, minute: int = 0, dst: bool = True):
    """產一個指定 ET 時間的 datetime,用來 patch datetime.now()。"""
    et = pytz.timezone("America/New_York")
    # 夏令時間:5/4 是 DST = True (US DST 從 3 月第 2 個週日起)
    # 冬令時間:1/15 是 DST = False
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
# resolve_actual_brief_type
# ------------------------------------------------------------

def test_resolve_us_premarket_intraday_switches():
    market = {"phase": "intraday", "is_dst": True, "et_time": "10:00 ET"}
    assert rmb.resolve_actual_brief_type("us_premarket", market) == \
        "us_premarket_to_intraday"


def test_resolve_us_premarket_premarket_unchanged():
    market = {"phase": "premarket", "is_dst": True, "et_time": "09:00 ET"}
    assert rmb.resolve_actual_brief_type("us_premarket", market) == "us_premarket"


def test_resolve_us_midday_afterhours_switches():
    market = {"phase": "afterhours", "is_dst": True, "et_time": "18:00 ET"}
    assert rmb.resolve_actual_brief_type("us_midday", market) == \
        "us_midday_to_afterhours"


def test_resolve_us_midday_intraday_unchanged():
    market = {"phase": "intraday", "is_dst": True, "et_time": "13:00 ET"}
    assert rmb.resolve_actual_brief_type("us_midday", market) == "us_midday"


def test_resolve_us_eod_never_changes():
    """us_eod / tw_eod 永遠原樣返回。"""
    for phase in ("premarket", "intraday", "afterhours"):
        market = {"phase": phase, "is_dst": True, "et_time": "X"}
        assert rmb.resolve_actual_brief_type("us_eod", market) == "us_eod"
        assert rmb.resolve_actual_brief_type("tw_eod", market) == "tw_eod"


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


def test_main_invalid_brief_type_returns_1(tmp_dedup, monkeypatch):
    monkeypatch.setenv("BRIEF_TYPE", "garbage")
    rc = rmb.main()
    assert rc == 1


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
