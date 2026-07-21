"""Deterministic SLA classification / session / copy tests for us_open.

Issue #13 / docs/market_brief_sla_v1.md. All times are injected; no wall clock
or network is touched. DST dates use July 2026 (U.S. daylight), standard dates
use January 2026 (U.S. standard).
"""

from datetime import datetime

import pytz

from src.runners.us_open_sla import (
    ACTION_SEND,
    ACTION_SKIP_EARLY,
    ACTION_SKIP_EXPIRED,
    ACTION_SKIP_WRONG_SESSION,
    LATE_MAX_MINUTES,
    ON_TIME_MAX_MINUTES,
    STATUS_EXPIRED,
    STATUS_INTRADAY_RECOVERY,
    STATUS_LATE,
    STATUS_ON_TIME,
    body_brief_type,
    classify_us_open,
    render_us_open_message,
    resolve_us_open_session,
    us_open_title,
)

TAIPEI = pytz.timezone("Asia/Taipei")

# 2026-07-20 Monday (U.S. daylight): open 21:30 Taipei / 09:30 ET.
# 2026-01-15 Thursday (U.S. standard): open 22:30 Taipei / 09:30 ET.
# 2026-07-18 Saturday: no session.


def _tpe(y, mo, d, h, mi=0):
    return TAIPEI.localize(datetime(y, mo, d, h, mi))


# --- constants --------------------------------------------------------------

def test_sla_thresholds_are_named_constants():
    assert ON_TIME_MAX_MINUTES == 10
    assert LATE_MAX_MINUTES == 30


# --- session resolution -----------------------------------------------------

def test_daylight_session_open_close_and_key():
    session = resolve_us_open_session(_tpe(2026, 7, 20, 21, 32))
    assert session.session_key == "us_open:2026-07-20"
    assert session.session_date_et == "2026-07-20"
    assert session.is_dst is True
    assert session.open_at_taipei.strftime("%Y-%m-%d %H:%M") == "2026-07-20 21:30"
    assert session.close_at_taipei.strftime("%Y-%m-%d %H:%M") == "2026-07-21 04:00"
    assert session.open_at_et.strftime("%H:%M") == "09:30"


def test_standard_session_open_close_and_key():
    session = resolve_us_open_session(_tpe(2026, 1, 15, 22, 32))
    assert session.session_key == "us_open:2026-01-15"
    assert session.is_dst is False
    assert session.open_at_taipei.strftime("%Y-%m-%d %H:%M") == "2026-01-15 22:30"
    assert session.close_at_taipei.strftime("%Y-%m-%d %H:%M") == "2026-01-16 05:00"


def test_late_evening_attempt_keeps_same_et_session_key():
    # 23:25 Taipei on the incident date is still the 2026-07-20 ET session.
    session = resolve_us_open_session(_tpe(2026, 7, 20, 23, 25))
    assert session.session_key == "us_open:2026-07-20"


# --- classification (daylight) ----------------------------------------------

def test_daylight_exact_open_is_on_time():
    decision = classify_us_open(_tpe(2026, 7, 20, 21, 30))
    assert decision.action == ACTION_SEND
    assert decision.status == STATUS_ON_TIME
    assert decision.lateness_minutes == 0


def test_daylight_plus_5_is_on_time():
    decision = classify_us_open(_tpe(2026, 7, 20, 21, 35))
    assert decision.status == STATUS_ON_TIME
    assert decision.lateness_minutes == 5


def test_daylight_plus_10_is_on_time_boundary():
    decision = classify_us_open(_tpe(2026, 7, 20, 21, 40))
    assert decision.status == STATUS_ON_TIME
    assert decision.lateness_minutes == 10


def test_daylight_plus_15_is_late():
    decision = classify_us_open(_tpe(2026, 7, 20, 21, 45))
    assert decision.status == STATUS_LATE
    assert decision.lateness_minutes == 15


def test_daylight_plus_35_is_intraday_recovery():
    decision = classify_us_open(_tpe(2026, 7, 20, 22, 5))
    assert decision.status == STATUS_INTRADAY_RECOVERY
    assert decision.lateness_minutes == 35


def test_daylight_plus_11_is_late():
    decision = classify_us_open(_tpe(2026, 7, 20, 21, 41))
    assert decision.status == STATUS_LATE
    assert decision.lateness_minutes == 11


def test_daylight_plus_30_is_late_boundary():
    decision = classify_us_open(_tpe(2026, 7, 20, 22, 0))
    assert decision.status == STATUS_LATE
    assert decision.lateness_minutes == 30


def test_daylight_plus_31_is_intraday_recovery():
    decision = classify_us_open(_tpe(2026, 7, 20, 22, 1))
    assert decision.status == STATUS_INTRADAY_RECOVERY
    assert decision.lateness_minutes == 31


def test_incident_2325_is_intraday_recovery_115_min():
    decision = classify_us_open(_tpe(2026, 7, 20, 23, 25))
    assert decision.action == ACTION_SEND
    assert decision.status == STATUS_INTRADAY_RECOVERY
    assert decision.lateness_minutes == 115


def test_daylight_before_open_is_early():
    decision = classify_us_open(_tpe(2026, 7, 20, 21, 0))
    assert decision.action == ACTION_SKIP_EARLY
    assert decision.status is None


def test_daylight_after_close_is_expired():
    # 04:30 Taipei next day = 16:30 ET, past the 16:00 ET close.
    decision = classify_us_open(_tpe(2026, 7, 21, 4, 30))
    assert decision.action == ACTION_SKIP_EXPIRED
    assert decision.status == STATUS_EXPIRED
    assert decision.session.session_key == "us_open:2026-07-20"


# --- classification (standard) ----------------------------------------------

def test_standard_exact_open_is_on_time():
    decision = classify_us_open(_tpe(2026, 1, 15, 22, 30))
    assert decision.status == STATUS_ON_TIME
    assert decision.lateness_minutes == 0


def test_standard_plus_20_is_late():
    decision = classify_us_open(_tpe(2026, 1, 15, 22, 50))
    assert decision.status == STATUS_LATE
    assert decision.lateness_minutes == 20


def test_standard_plus_40_is_intraday_recovery():
    decision = classify_us_open(_tpe(2026, 1, 15, 23, 10))
    assert decision.status == STATUS_INTRADAY_RECOVERY
    assert decision.lateness_minutes == 40


# --- wrong-DST cron self-skip at runtime ------------------------------------

def test_daylight_cron_during_standard_time_self_skips_as_early():
    # The 21:32 Taipei (13:32 UTC) daylight attempt fires at 08:32 ET in winter,
    # which the runtime classifier treats as before-open, not a wrong send.
    decision = classify_us_open(_tpe(2026, 1, 15, 21, 32))
    assert decision.action == ACTION_SKIP_EARLY


# --- weekend ----------------------------------------------------------------

def test_saturday_is_wrong_session():
    decision = classify_us_open(_tpe(2026, 7, 18, 21, 32))
    assert decision.action == ACTION_SKIP_WRONG_SESSION
    assert decision.session is None


# --- titles -----------------------------------------------------------------

def test_on_time_title_is_plain_open_brief():
    assert us_open_title(STATUS_ON_TIME, 0) == "🚀 美股開盤 brief"


def test_late_title_discloses_minutes():
    title = us_open_title(STATUS_LATE, 18)
    assert "延遲補發" in title
    assert "18" in title


def test_intraday_recovery_title_is_midday_makeup():
    title = us_open_title(STATUS_INTRADAY_RECOVERY, 115)
    assert "盤中補發" in title
    assert "115" in title


# --- phase-aware body selection ---------------------------------------------

def test_body_type_on_time_and_late_use_us_open():
    assert body_brief_type(STATUS_ON_TIME) == "us_open"
    assert body_brief_type(STATUS_LATE) == "us_open"


def test_body_type_intraday_recovery_uses_midday():
    # >30 min late is well into the session; the premarket/open body is stale.
    assert body_brief_type(STATUS_INTRADAY_RECOVERY) == "us_midday"


# --- message rendering ------------------------------------------------------

_LEGACY_BODY = (
    "<b>🚀 美股開盤 brief</b>\n\nBODY-CONTENT-XYZ"
    "\n\n<i>下次 brief: 美股盤中</i>"
)


def test_render_on_time_replaces_legacy_title_keeps_body():
    decision = classify_us_open(_tpe(2026, 7, 20, 21, 32))
    message = render_us_open_message(_LEGACY_BODY, decision)
    assert message.startswith("<b>🚀 美股開盤 brief</b>")
    assert "BODY-CONTENT-XYZ" in message
    assert "延遲補發" not in message
    # legacy inner title removed (only one bold title at the very start).
    assert message.count("🚀 美股開盤 brief") == 1
    assert "下次 brief" in message


def test_render_late_shows_delay_and_recompute_note():
    decision = classify_us_open(_tpe(2026, 7, 20, 21, 48))  # +18
    message = render_us_open_message(_LEGACY_BODY, decision)
    assert "延遲補發（晚 18 分鐘）" in message
    assert "重新計算" in message
    assert "BODY-CONTENT-XYZ" in message


def test_render_intraday_recovery_shows_makeup_title():
    decision = classify_us_open(_tpe(2026, 7, 20, 23, 25))  # +115
    message = render_us_open_message(_LEGACY_BODY, decision)
    assert "盤中補發" in message
    assert "115" in message
