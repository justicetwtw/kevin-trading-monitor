"""Phase 2.5.5 — brief sanity check 測試。"""

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
    """週五 23:00 → 4 種 brief 都該已推。"""
    fri_23 = _taipei(2026, 5, 8, 23, 0)
    expected = rbs._expected_today(fri_23)
    assert set(expected) == {"us_eod", "tw_eod", "us_premarket", "us_midday"}


def test_expected_today_monday_full_day():
    """週一 23:00 → tw_eod + us_premarket + us_midday(週一無 us_eod,因為 cron 是 Tue-Sat)。

    us_midday cron 是 Tue-Sat,週一也不該有。
    所以週一 23:00 預期:tw_eod + us_premarket。
    """
    mon_23 = _taipei(2026, 5, 4, 23, 0)
    expected = rbs._expected_today(mon_23)
    assert "tw_eod" in expected
    assert "us_premarket" in expected
    assert "us_eod" not in expected
    assert "us_midday" not in expected


def test_expected_today_saturday():
    """週六 → 只有 us_eod / us_midday(無 tw_eod / us_premarket)。"""
    sat_23 = _taipei(2026, 5, 9, 23, 0)
    expected = rbs._expected_today(sat_23)
    assert "us_eod" in expected
    assert "us_midday" in expected
    assert "tw_eod" not in expected
    assert "us_premarket" not in expected


def test_expected_today_sunday_empty():
    """週日 cron 都不跑 → 預期空。"""
    sun = _taipei(2026, 5, 10, 23, 0)
    expected = rbs._expected_today(sun)
    assert expected == []


def test_expected_today_before_midday_window_empty():
    """週二 07:00(us_midday 視窗 08:00 前)→ 預期空。"""
    tue_7 = _taipei(2026, 5, 5, 7, 0)
    assert rbs._expected_today(tue_7) == []


def test_expected_today_at_midday_window_only_midday():
    """週二 08:00(剛進入 us_midday 視窗)→ 只有 us_midday。"""
    tue_8 = _taipei(2026, 5, 5, 8, 0)
    assert rbs._expected_today(tue_8) == ["us_midday"]


def test_main_no_missing_no_alert(tmp_dedup, monkeypatch):
    """全部該推的都推了 → 不發告警。"""
    today_str = datetime.now(rbs.TIMEZONE_USER).strftime("%Y-%m-%d")
    tmp_dedup.parent.mkdir(parents=True, exist_ok=True)
    tmp_dedup.write_text(
        json.dumps({today_str: {
            "us_eod": True, "tw_eod": True,
            "us_premarket": True, "us_midday": True,
        }}),
        encoding="utf-8",
    )
    with patch.object(rbs, "send_telegram") as mock_send:
        rc = rbs.main()
    assert rc == 0
    mock_send.assert_not_called()


def test_main_sends_alert_when_missing(tmp_dedup, monkeypatch):
    """週五晚上但 dedup file 不存在 → 該全部 missing → 發告警。"""
    fri_23 = _taipei(2026, 5, 8, 23, 30)
    with patch.object(rbs, "datetime") as mock_dt, \
         patch.object(rbs, "send_telegram", return_value=True) as mock_send:
        mock_dt.now.return_value = fri_23
        # _load_sent_today 的 datetime.now 也走同個 patch
        mock_dt.strptime = datetime.strptime
        rc = rbs.main()
    assert rc == 0
    mock_send.assert_called_once()
    # 告警內容應提及 4 種 brief
    args, _ = mock_send.call_args
    msg = args[0]
    assert "Brief 觸發異常" in msg
    for bt in ("us_eod", "tw_eod", "us_premarket", "us_midday"):
        assert bt in msg
