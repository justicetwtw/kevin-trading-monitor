"""Brief sanity check tests using canonical Asia/Taipei dispatch windows.

Regular market times:
- Taiwan: 09:00-13:30 Taipei.
- U.S. daylight: 21:30-04:00 next day Taipei.
- U.S. standard: 22:30-05:00 next day Taipei.

The sanity job runs at 23:45 / 23:55 and checks all briefs that should already
have arrived on that Taipei calendar date, including the 01:00 / 02:00 U.S.
midday brief and the 04:30 / 05:30 U.S. EOD brief on Tue-Sat.
"""

import json
from datetime import datetime
from unittest.mock import patch

import pytest
import pytz

from src.runners import run_brief_sanity as rbs


@pytest.fixture
def tmp_dedup(tmp_path, monkeypatch):
    path = tmp_path / "data_store" / "brief_sent_today.json"
    monkeypatch.setattr(rbs, "DEDUP_PATH", path)
    # Isolate the us_open delivery-state reader from the committed real file.
    monkeypatch.setattr(
        rbs, "US_OPEN_STATE_PATH", tmp_path / "data_store" / "us_open_state.json"
    )
    return path


def _taipei(year, month, day, hour, minute=0):
    timezone = pytz.timezone("Asia/Taipei")
    return timezone.localize(datetime(year, month, day, hour, minute))


def test_expected_today_friday_full_day():
    """Friday late sanity includes overnight U.S. and local daytime briefs."""
    friday = _taipei(2026, 5, 8, 23, 45)
    expected = set(rbs._expected_today(friday))
    assert expected == {
        "us_midday",
        "us_eod",
        "tw_open",
        "tw_close",
        "us_premarket",
        "us_open",
    }


def test_expected_today_monday_full_day():
    """Monday has no prior Sunday-night U.S. session briefs."""
    monday = _taipei(2026, 5, 4, 23, 45)
    expected = set(rbs._expected_today(monday))
    assert expected == {
        "tw_open",
        "tw_close",
        "us_premarket",
        "us_open",
    }
    assert "tw_eod" not in expected


def test_expected_today_saturday():
    """Saturday receives Friday U.S. midday and EOD briefs only."""
    saturday = _taipei(2026, 5, 9, 23, 45)
    assert rbs._expected_today(saturday) == ["us_midday", "us_eod"]


def test_expected_today_sunday_empty():
    sunday = _taipei(2026, 5, 10, 23, 45)
    assert rbs._expected_today(sunday) == []


def test_expected_today_after_midday_before_eod():
    """Tuesday 06:00 has the overnight midday brief but EOD grace ends at 07:00."""
    tuesday_6 = _taipei(2026, 5, 5, 6, 0)
    assert rbs._expected_today(tuesday_6) == ["us_midday"]


def test_expected_today_at_us_eod_window():
    """Tuesday 07:00 expects both overnight U.S. briefs."""
    tuesday_7 = _taipei(2026, 5, 5, 7, 0)
    assert rbs._expected_today(tuesday_7) == ["us_midday", "us_eod"]


def test_main_no_missing_no_alert(tmp_dedup, monkeypatch):
    today_str = datetime.now(rbs.TIMEZONE_USER).strftime("%Y-%m-%d")
    tmp_dedup.parent.mkdir(parents=True, exist_ok=True)
    tmp_dedup.write_text(
        json.dumps(
            {
                today_str: {
                    "us_eod": True,
                    "tw_open": True,
                    "tw_close": True,
                    "us_premarket": True,
                    "us_open": True,
                    "us_midday": True,
                }
            }
        ),
        encoding="utf-8",
    )
    with patch.object(rbs, "send_telegram") as mock_send:
        result = rbs.main()
    assert result == 0
    mock_send.assert_not_called()


def _today_session():
    """Session whose ET date equals today's Taipei date (as at 23:45 sanity)."""
    from src.runners.us_open_sla import resolve_us_open_session

    base = datetime.now(rbs.TIMEZONE_USER).date()
    evening = rbs.TIMEZONE_USER.localize(
        datetime(base.year, base.month, base.day, 22, 0)
    )
    return resolve_us_open_session(evening)


def test_us_open_sent_via_new_state_is_not_flagged_missing(tmp_dedup):
    """us_open completion is read from the SLA delivery state, not the boolean."""
    from src.runners.us_open_state import (
        DELIVERY_SENT,
        UsOpenDeliveryStore,
        new_record,
    )

    session = _today_session()
    store = UsOpenDeliveryStore(rbs.US_OPEN_STATE_PATH, legacy_path=None)
    store.upsert(new_record(
        session, status="on_time", lateness_minutes=1,
        schedule_source="cron", workflow_run_id="r",
        workflow_started_at=session.open_at_taipei.isoformat(),
        delivery_state=DELIVERY_SENT,
    ))
    # No legacy us_open entry at all.
    sent = rbs._load_sent_today()
    assert sent.get("us_open") is True


def test_us_open_missing_in_both_states_is_flagged(tmp_dedup):
    from src.runners.us_open_state import (
        DELIVERY_FAILED,
        UsOpenDeliveryStore,
        new_record,
    )

    session = _today_session()
    store = UsOpenDeliveryStore(rbs.US_OPEN_STATE_PATH, legacy_path=None)
    # a failed (not sent) record must NOT count as delivered
    store.upsert(new_record(
        session, status="failed", lateness_minutes=None,
        schedule_source="cron", workflow_run_id="r",
        workflow_started_at=session.open_at_taipei.isoformat(),
        delivery_state=DELIVERY_FAILED,
    ))
    sent = rbs._load_sent_today()
    assert sent.get("us_open") is not True


def test_us_open_corrupt_state_degrades_without_crashing(tmp_dedup):
    """A corrupt us_open delivery state must not crash the sanity check."""
    rbs.US_OPEN_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    rbs.US_OPEN_STATE_PATH.write_text('{"sessions": []}', encoding="utf-8")
    sent = rbs._load_sent_today()  # must not raise
    assert sent.get("us_open") is not True  # reported as not-delivered (degraded)


def test_main_sends_alert_when_missing(tmp_dedup, monkeypatch):
    """Friday late sanity reports every missing brief, including us_midday."""
    friday = _taipei(2026, 5, 8, 23, 45)
    with patch.object(rbs, "datetime") as mock_datetime, patch.object(
        rbs, "send_telegram", return_value=True
    ) as mock_send:
        mock_datetime.now.return_value = friday
        mock_datetime.strptime = datetime.strptime
        result = rbs.main()
    assert result == 0
    mock_send.assert_called_once()
    message = mock_send.call_args.args[0]
    assert "Brief 觸發異常" in message
    for brief_type in (
        "us_midday",
        "us_eod",
        "tw_open",
        "tw_close",
        "us_premarket",
        "us_open",
    ):
        assert brief_type in message
