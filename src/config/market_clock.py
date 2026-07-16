"""Taiwan-first market time definitions and formatting.

All user-facing times are Asia/Taipei. GitHub Actions cron remains UTC, but
workflow comments and dispatch gates must map back to these canonical sessions.

Regular sessions (excluding holidays / special early closes):
- TWSE/TPEx: 09:00-13:30 Asia/Taipei.
- NYSE/Nasdaq core: 09:30-16:00 America/New_York.
  In Taipei this is 21:30-next day 04:00 during U.S. daylight time and
  22:30-next day 05:00 during U.S. standard time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

import pytz

TAIPEI = pytz.timezone("Asia/Taipei")
NEW_YORK = pytz.timezone("America/New_York")

TW_REGULAR_OPEN = time(9, 0)
TW_REGULAR_CLOSE = time(13, 30)
US_REGULAR_OPEN_ET = time(9, 30)
US_REGULAR_CLOSE_ET = time(16, 0)


@dataclass(frozen=True)
class SessionWindow:
    market: str
    open_at: datetime
    close_at: datetime

    @property
    def is_open(self) -> bool:
        now = datetime.now(self.open_at.tzinfo)
        return self.open_at <= now < self.close_at


def _localize(zone, day: date, clock: time) -> datetime:
    return zone.localize(datetime.combine(day, clock))


def taiwan_regular_session(day: date) -> SessionWindow:
    """Return the regular Taiwan equity session in Asia/Taipei."""
    return SessionWindow(
        market="TW",
        open_at=_localize(TAIPEI, day, TW_REGULAR_OPEN),
        close_at=_localize(TAIPEI, day, TW_REGULAR_CLOSE),
    )


def us_regular_session_for_eastern_date(day: date) -> SessionWindow:
    """Return one U.S. core session converted to Asia/Taipei."""
    open_et = _localize(NEW_YORK, day, US_REGULAR_OPEN_ET)
    close_et = _localize(NEW_YORK, day, US_REGULAR_CLOSE_ET)
    return SessionWindow(
        market="US",
        open_at=open_et.astimezone(TAIPEI),
        close_at=close_et.astimezone(TAIPEI),
    )


def is_us_regular_market_hours(now: datetime | None = None) -> bool:
    """Return True only during the U.S. 09:30-16:00 ET regular session.

    This checks weekday and clock time. Exchange holidays and special early
    closes require an exchange calendar and are intentionally not fabricated.
    """
    current = now or datetime.now(NEW_YORK)
    if current.tzinfo is None:
        current = NEW_YORK.localize(current)
    current_et = current.astimezone(NEW_YORK)
    if current_et.weekday() >= 5:
        return False
    current_clock = current_et.time().replace(tzinfo=None)
    return US_REGULAR_OPEN_ET <= current_clock < US_REGULAR_CLOSE_ET


def is_us_dst_active(reference: datetime | None = None) -> bool:
    current = reference or datetime.now(NEW_YORK)
    if current.tzinfo is None:
        current = NEW_YORK.localize(current)
    return current.astimezone(NEW_YORK).dst().total_seconds() > 0


def canonical_market_hours_text() -> str:
    return (
        "台股正式交易 09:00-13:30（台北）；"
        "美股正式交易 夏令 21:30-翌日04:00、"
        "冬令 22:30-翌日05:00（台北）"
    )


# Brief identifiers are retained for compatibility, but the display copy must
# describe what the message actually is. `tw_open` runs at 08:30, so it is a
# pre-open brief, not the exchange opening time.
BRIEF_DISPLAY_TITLE = {
    "us_eod": "📊 美股收盤後 brief",
    "tw_open": "🇹🇼 台股盤前 brief（正式開盤 09:00）",
    "tw_close": "🇹🇼 台股收盤後 brief（正式收盤 13:30）",
    "us_premarket": "🌎 美股盤前觀察 brief",
    "us_open": "🚀 美股開盤 brief",
    "us_midday": "🌃 美股盤中 brief",
}

BRIEF_TIME_NOTE = {
    "us_eod": (
        "美股正式收盤：夏令翌日 04:00／冬令翌日 05:00；"
        "本 brief 於收盤後約 30 分鐘發送"
    ),
    "tw_open": "台股正式交易 09:00-13:30；本 brief 於 08:30 盤前發送",
    "tw_close": "台股正式收盤 13:30；本 brief 於收盤後約 10 分鐘發送",
    "us_premarket": (
        "美股核心交易夏令 21:30／冬令 22:30 開盤；"
        "本訊息是盤前觀察，不是開盤通知"
    ),
    "us_open": (
        "美股正式開盤：夏令 21:30／冬令 22:30；"
        "正式收盤：夏令翌日 04:00／冬令翌日 05:00"
    ),
    "us_midday": "美股盤中觀察；核心交易時段以台北時間為準",
}

NEXT_BRIEF_LABEL = {
    "us_eod": "台股盤前 brief（08:30；正式開盤 09:00）",
    "tw_open": "台股收盤後 brief（13:40；正式收盤 13:30）",
    "tw_close": "美股盤前觀察（夏令 17:00／冬令 18:00）",
    "us_premarket": "美股正式開盤（夏令 21:30／冬令 22:30）",
    "us_open": "美股盤中 brief（夏令翌日 01:00／冬令翌日 02:00）",
    "us_midday": "美股收盤後 brief（夏令翌日 04:30／冬令翌日 05:30）",
}


def normalize_market_brief_copy(message: str, brief_type: str) -> str:
    """Correct legacy hard-coded titles/footer and add canonical Taipei times."""
    title = BRIEF_DISPLAY_TITLE.get(brief_type, brief_type)
    note = BRIEF_TIME_NOTE.get(brief_type, canonical_market_hours_text())
    next_label = NEXT_BRIEF_LABEL.get(brief_type, "")

    body = message
    if body.startswith("<b>") and "</b>" in body:
        body = body.split("</b>", 1)[1].lstrip("\n")
    marker = "\n\n<i>下次 brief:"
    if marker in body:
        body = body.split(marker, 1)[0]

    footer = f"\n\n<i>下次 brief: {next_label}</i>" if next_label else ""
    return (
        f"<b>{title}</b>\n"
        f"<i>市場時間基準：{note}</i>\n\n"
        f"{body}{footer}"
    )


def session_snapshot(reference: datetime | None = None) -> dict[str, Any]:
    """Return canonical market-hour metadata for diagnostics/dashboard."""
    now_tpe = reference or datetime.now(TAIPEI)
    if now_tpe.tzinfo is None:
        now_tpe = TAIPEI.localize(now_tpe)
    now_et = now_tpe.astimezone(NEW_YORK)
    us_session = us_regular_session_for_eastern_date(now_et.date())
    tw_session = taiwan_regular_session(now_tpe.date())
    return {
        "timezone": "Asia/Taipei",
        "now": now_tpe.isoformat(),
        "tw_regular_open": tw_session.open_at.isoformat(),
        "tw_regular_close": tw_session.close_at.isoformat(),
        "us_regular_open": us_session.open_at.isoformat(),
        "us_regular_close": us_session.close_at.isoformat(),
        "us_dst": is_us_dst_active(now_et),
        "holiday_aware": False,
        "limitation": (
            "Regular-session clock is exact; exchange holidays and special "
            "early closes require a separate exchange-calendar source."
        ),
    }
