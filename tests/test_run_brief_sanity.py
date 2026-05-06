"""Phase 2.5.5 + Sprint 2.5.9 — brief sanity check 測試。

新時間表(夏令):us_eod 05:30 / tw_open 08:30 / tw_close 13:30 /
us_premarket 17:00 / us_open 22:00 / us_midday 02:00 (隔日)
sanity 在 23:00 跑 → 當日預期含 us_eod / tw_open / tw_close /
us_premarket / us_open(us_midday 在 02:00 隔日,不在當日視窗)。
"""

import json
from datetime import datetime
from unittest.mock import patch

import pytest
import pytz

from src.runners import run_brief_sanity as rbs


@pytest.fixture
def tmp_dedup(tmp_path, monkeypatch):
    p = tmp_path / "data_store" / "brief_sent_today.json"
    monkeypatch.setattr(rbs, "DEDUP_PATH", p)
    return p


def _taipei(year, month, day, hour, minute=0):
    tz = pytz.timezone("Asia/Taipei")
    return tz.localize(datetime(year, month, day, hour, minute))


def test_expected_today_friday_full_day():
    """週五 23:00 → us_eod + tw_open + tw_close + us_premarket + us_open。"""
    fri_23 = _taipei(2026, 5, 8, 23, 0)
    expected = rbs._expected_today(fri_23)
    assert set(expected) == {
        "us_eod", "tw_open", "tw_close", "us_premarket", "us_open",
    }


def test_expected_today_monday_full_day():
    """週一 23:00 → tw_open + tw_close + us_premarket + us_open
    (週一 us_eod 視窗在週日 cron 推送之外,故無;us_midday 不在當日)。
    """
    mon_23 = _taipei(2026, 5, 4, 23, 0)
    expected = rbs._expected_today(mon_23)
    assert "tw_open" in expected
    assert "tw_close" in expected
    assert "us_premarket" in expected
    assert "us_open" in expected
    assert "us_eod" not in expected
    # tw_eod 已 retire
    assert "tw_eod" not in expected


def test_expected_today_saturday():
    """週六 → 只有 us_eod(週五美股收盤推送);無 tw_*、us_premarket、us_open。"""
    sat_23 = _taipei(2026, 5, 9, 23, 0)
    expected = rbs._expected_today(sat_23)
    assert expected == ["us_eod"]


def test_expected_today_sunday_empty():
    sun = _taipei(2026, 5, 10, 23, 0)
    expected = rbs._expected_today(sun)
    assert expected == []


def test_expected_today_before_us_eod_window_empty():
    """週二 06:00(us_eod 視窗 07:00 前)→ 預期空。"""
    tue_6 = _taipei(2026, 5, 5, 6, 0)
    assert rbs._expected_today(tue_6) == []


def test_expected_today_at_us_eod_window_only_us_eod():
    """週二 07:00(剛進入 us_eod 視窗)→ 只有 us_eod。"""
    tue_7 = _taipei(2026, 5, 5, 7, 0)
    assert rbs._expected_today(tue_7) == ["us_eod"]


def test_main_no_missing_no_alert(tmp_dedup, monkeypatch):
    today_str = datetime.now(rbs.TIMEZONE_USER).strftime("%Y-%m-%d")
    tmp_dedup.parent.mkdir(parents=True, exist_ok=True)
    tmp_dedup.write_text(
        json.dumps({today_str: {
            "us_eod": True, "tw_open": True, "tw_close": True,
            "us_premarket": True, "us_open": True, "us_midday": True,
        }}),
        encoding="utf-8",
    )
    with patch.object(rbs, "send_telegram") as mock_send:
        rc = rbs.main()
    assert rc == 0
    mock_send.assert_not_called()


def test_main_sends_alert_when_missing(tmp_dedup, monkeypatch):
    """週五晚上但 dedup file 不存在 → 全部 missing → 發告警。"""
    fri_23 = _taipei(2026, 5, 8, 23, 30)
    with patch.object(rbs, "datetime") as mock_dt, \
         patch.object(rbs, "send_telegram", return_value=True) as mock_send:
        mock_dt.now.return_value = fri_23
        mock_dt.strptime = datetime.strptime
        rc = rbs.main()
    assert rc == 0
    mock_send.assert_called_once()
    args, _ = mock_send.call_args
    msg = args[0]
    assert "Brief 觸發異常" in msg
    for bt in ("us_eod", "tw_open", "tw_close", "us_premarket", "us_open"):
        assert bt in msg
