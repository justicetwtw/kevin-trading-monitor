"""Regression tests for Taiwan-first market hours and brief copy."""

from datetime import date, datetime
from pathlib import Path

from src.config.market_clock import (
    NEW_YORK,
    TAIPEI,
    canonical_market_hours_text,
    is_us_regular_market_hours,
    normalize_market_brief_copy,
    taiwan_regular_session,
    us_regular_session_for_eastern_date,
)
from src.runners.run_brief_sanity import _expected_today


def test_taiwan_regular_session_is_0900_to_1330_taipei():
    session = taiwan_regular_session(date(2026, 7, 16))
    assert session.open_at.tzinfo.zone == "Asia/Taipei"
    assert session.open_at.strftime("%H:%M") == "09:00"
    assert session.close_at.strftime("%H:%M") == "13:30"


def test_us_summer_session_converts_to_2130_and_next_day_0400_taipei():
    session = us_regular_session_for_eastern_date(date(2026, 7, 16))
    assert session.open_at.strftime("%Y-%m-%d %H:%M") == "2026-07-16 21:30"
    assert session.close_at.strftime("%Y-%m-%d %H:%M") == "2026-07-17 04:00"


def test_us_winter_session_converts_to_2230_and_next_day_0500_taipei():
    session = us_regular_session_for_eastern_date(date(2026, 12, 15))
    assert session.open_at.strftime("%Y-%m-%d %H:%M") == "2026-12-15 22:30"
    assert session.close_at.strftime("%Y-%m-%d %H:%M") == "2026-12-16 05:00"


def test_us_regular_market_gate_uses_eastern_core_session():
    inside = NEW_YORK.localize(datetime(2026, 7, 16, 9, 30))
    before = NEW_YORK.localize(datetime(2026, 7, 16, 9, 29))
    close = NEW_YORK.localize(datetime(2026, 7, 16, 16, 0))
    weekend = NEW_YORK.localize(datetime(2026, 7, 18, 12, 0))
    assert is_us_regular_market_hours(inside) is True
    assert is_us_regular_market_hours(before) is False
    assert is_us_regular_market_hours(close) is False
    assert is_us_regular_market_hours(weekend) is False


def test_brief_copy_does_not_call_0830_taiwan_market_open():
    legacy = (
        "<b>🇹🇼 台股開盤 brief</b>\n\nbody"
        "\n\n<i>下次 brief: 台股收盤 (台北 13:30)</i>"
    )
    message = normalize_market_brief_copy(legacy, "tw_open")
    assert "台股盤前 brief" in message
    assert "正式開盤 09:00" in message
    assert "08:30 盤前" in message


def test_us_open_copy_uses_2130_summer_2230_winter():
    legacy = "<b>🚀 美股開盤 brief</b>\n\nbody"
    message = normalize_market_brief_copy(legacy, "us_open")
    assert "夏令 21:30" in message
    assert "冬令 22:30" in message
    assert "翌日 04:00" in message
    assert "翌日 05:00" in message


def test_canonical_text_is_taipei_first():
    text = canonical_market_hours_text()
    assert "台股正式交易 09:00-13:30" in text
    assert "美股正式交易 夏令 21:30-翌日04:00" in text
    assert "冬令 22:30-翌日05:00" in text


def test_workflow_crons_match_exact_us_open_and_close():
    market_brief = Path(".github/workflows/market_brief.yml").read_text(
        encoding="utf-8"
    )
    eod = Path(".github/workflows/signal_scan_eod.yml").read_text(
        encoding="utf-8"
    )
    sanity = Path(".github/workflows/brief_sanity.yml").read_text(
        encoding="utf-8"
    )
    assert "30 20 * * 1-5" in market_brief  # 04:30 Taipei DST EOD brief
    assert "30 21 * * 1-5" in market_brief  # 05:30 Taipei standard EOD brief
    assert "15 20 * * 1-5" in eod            # 04:15 Taipei DST EOD scan
    assert "15 21 * * 1-5" in eod            # 05:15 Taipei standard EOD scan
    assert "45 15 * * *" in sanity            # 23:45 Taipei sanity
    assert "55 15 * * *" in sanity            # 23:55 Taipei backup


def test_us_open_moved_to_isolated_dedicated_workflow():
    """Issue #13: us_open must leave the shared `market-brief` concurrency queue."""
    market_brief = Path(".github/workflows/market_brief.yml").read_text(
        encoding="utf-8"
    )
    us_open = Path(".github/workflows/us_open_brief.yml").read_text(
        encoding="utf-8"
    )
    # The old single-shot open crons no longer share the broad brief queue.
    assert "30 13 * * 1-5" not in market_brief
    assert "30 14 * * 1-5" not in market_brief
    # us_open is no longer dispatched or routed by the shared workflow.
    assert "- us_open" not in market_brief  # not a dispatch choice anymore
    assert 'BT="us_open"' not in market_brief  # no DST case branch anymore
    # The dedicated watchdog owns the open with staggered attempts and an
    # isolated concurrency group.
    assert "group: us-open-brief" in us_open
    assert "cancel-in-progress: false" in us_open
    for dst_attempt in ("32 13 * * 1-5", "39 13 * * 1-5", "48 13 * * 1-5"):
        assert dst_attempt in us_open  # daylight open +2/+9/+18
    for std_attempt in ("32 14 * * 1-5", "39 14 * * 1-5", "48 14 * * 1-5"):
        assert std_attempt in us_open  # standard open +2/+9/+18
    # durable claim before send + real (pre-setup) workflow-start timestamp.
    assert "US_OPEN_DURABLE_STATE" in us_open
    assert "US_OPEN_WORKFLOW_STARTED_AT" in us_open
    # unique per-attempt identity so a re-run cannot steal a prior claim.
    assert "GITHUB_RUN_ATTEMPT" in us_open
    # the start timestamp is captured before dependency install.
    start_idx = us_open.index("US_OPEN_WORKFLOW_STARTED_AT")
    install_idx = us_open.index("Install dependencies")
    assert start_idx < install_idx
    # a hung run must not starve backups: the job is time-bounded.
    assert "timeout-minutes:" in us_open


def test_tuesday_late_sanity_checks_overnight_and_local_briefs():
    now = TAIPEI.localize(datetime(2026, 7, 14, 23, 45))  # Tuesday
    expected = set(_expected_today(now))
    assert {
        "us_midday",
        "us_eod",
        "tw_open",
        "tw_close",
        "us_premarket",
        "us_open",
    } <= expected


def test_monday_late_sanity_does_not_expect_prior_weekend_us_briefs():
    now = TAIPEI.localize(datetime(2026, 7, 13, 23, 45))  # Monday
    expected = set(_expected_today(now))
    assert "us_midday" not in expected
    assert "us_eod" not in expected
    assert {"tw_open", "tw_close", "us_premarket", "us_open"} <= expected
