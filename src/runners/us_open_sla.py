"""U.S. opening-brief SLA classification, session resolution and copy.

Issue #13 / ``docs/market_brief_sla_v1.md``.

Everything here is deterministic and side-effect free so delay, DST and
market-phase behaviour can be proven without network or wall-clock access.
``now`` is always injected; a cron label is never trusted as proof of the
market phase — the runtime New York session is recomputed from the clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.config.market_clock import (
    NEW_YORK,
    TAIPEI,
    US_REGULAR_CLOSE_ET,
    US_REGULAR_OPEN_ET,
    is_us_dst_active,
)

BRIEF_TYPE = "us_open"

# SLA thresholds measured in minutes from the 09:30 ET regular open.
# These are constants with deterministic tests, never hidden in copy strings
# (contract section 2).
ON_TIME_MAX_MINUTES = 10  # open .. +10 inclusive
LATE_MAX_MINUTES = 30  # (+10 .. +30] inclusive

# Delivery status vocabulary (contract section 4 ``status``).
STATUS_ON_TIME = "on_time"
STATUS_LATE = "late"
STATUS_INTRADAY_RECOVERY = "intraday_recovery"
STATUS_EXPIRED = "expired"
STATUS_SKIPPED_DUPLICATE = "skipped_duplicate"
STATUS_SKIPPED_WRONG_SESSION = "skipped_wrong_session"
STATUS_FAILED = "failed"

# Runner action for a single attempt.
ACTION_SEND = "send"
ACTION_SKIP_EARLY = "skip_early"  # before the open; wait for a later attempt
ACTION_SKIP_EXPIRED = "skip_expired"  # session closed; never fake an open brief
ACTION_SKIP_WRONG_SESSION = "skip_wrong_session"  # weekend / not a trading day


@dataclass(frozen=True)
class UsOpenSession:
    """The U.S. regular-open session an attempt maps to, computed at runtime."""

    session_date_et: str  # YYYY-MM-DD (ET calendar date of the open)
    session_key: str  # us_open:YYYY-MM-DD
    open_at_taipei: datetime
    close_at_taipei: datetime
    open_at_et: datetime
    close_at_et: datetime
    is_dst: bool


@dataclass(frozen=True)
class UsOpenDecision:
    action: str  # ACTION_*
    status: str | None  # STATUS_* for send/expired, else None
    lateness_minutes: int | None
    session: UsOpenSession | None
    reason: str  # short log string


def _as_et(now: datetime) -> datetime:
    """Return ``now`` as an America/New_York-aware datetime."""
    if now.tzinfo is None:
        now = NEW_YORK.localize(now)
    return now.astimezone(NEW_YORK)


def resolve_us_open_session(now: datetime) -> UsOpenSession:
    """Compute the U.S. regular-open session for the ET calendar date of ``now``.

    The open/close are localized from 09:30 / 16:00 ET (never in a DST gap), so
    this holds across daylight and standard time without trusting a cron label.
    """
    now_et = _as_et(now)
    session_date = now_et.date()
    open_et = NEW_YORK.localize(
        datetime.combine(session_date, US_REGULAR_OPEN_ET)
    )
    close_et = NEW_YORK.localize(
        datetime.combine(session_date, US_REGULAR_CLOSE_ET)
    )
    return UsOpenSession(
        session_date_et=session_date.isoformat(),
        session_key=f"{BRIEF_TYPE}:{session_date.isoformat()}",
        open_at_taipei=open_et.astimezone(TAIPEI),
        close_at_taipei=close_et.astimezone(TAIPEI),
        open_at_et=open_et,
        close_at_et=close_et,
        is_dst=is_us_dst_active(now_et),
    )


def _minutes(delta_seconds: float) -> int:
    """Floor a positive second delta to whole minutes."""
    return int(delta_seconds // 60)


def classify_us_open(now: datetime) -> UsOpenDecision:
    """Decide what a single U.S.-open attempt at ``now`` should do.

    The runner — not the cron schedule — is the source of truth for whether the
    attempt is early, on time, late, an intraday recovery, expired or on a
    non-trading day. Exchange holidays are intentionally NOT detected (that
    needs an exchange-calendar source, which cannot be added without approval);
    only weekends are treated as wrong-session.
    """
    now_et = _as_et(now)

    # Weekend guard. Saturday=5, Sunday=6.
    if now_et.weekday() >= 5:
        return UsOpenDecision(
            action=ACTION_SKIP_WRONG_SESSION,
            status=STATUS_SKIPPED_WRONG_SESSION,
            lateness_minutes=None,
            session=None,
            reason="weekend: no U.S. regular session",
        )

    session = resolve_us_open_session(now)

    if now_et < session.open_at_et:
        minutes_to_open = _minutes(
            (session.open_at_et - now_et).total_seconds()
        )
        return UsOpenDecision(
            action=ACTION_SKIP_EARLY,
            status=None,
            lateness_minutes=None,
            session=session,
            reason=f"{minutes_to_open} min before open; wait for a later attempt",
        )

    lateness = _minutes((now_et - session.open_at_et).total_seconds())

    if now_et >= session.close_at_et:
        return UsOpenDecision(
            action=ACTION_SKIP_EXPIRED,
            status=STATUS_EXPIRED,
            lateness_minutes=lateness,
            session=session,
            reason="regular session closed; do not fake an opening brief",
        )

    if lateness <= ON_TIME_MAX_MINUTES:
        status = STATUS_ON_TIME
    elif lateness <= LATE_MAX_MINUTES:
        status = STATUS_LATE
    else:
        status = STATUS_INTRADAY_RECOVERY

    return UsOpenDecision(
        action=ACTION_SEND,
        status=status,
        lateness_minutes=lateness,
        session=session,
        reason=f"send {status} (+{lateness}m from open)",
    )


# --- user-facing copy -------------------------------------------------------

_ON_TIME_TITLE = "🚀 美股開盤 brief"


def us_open_title(status: str, lateness_minutes: int | None) -> str:
    """Title that reflects the *actual* delivery phase (contract section 5)."""
    late = lateness_minutes if lateness_minutes is not None else 0
    if status == STATUS_ON_TIME:
        return _ON_TIME_TITLE
    if status == STATUS_LATE:
        return f"⚠️ 美股開盤 brief 延遲補發（晚 {late} 分鐘）"
    if status == STATUS_INTRADAY_RECOVERY:
        return f"⚠️ 美股盤中補發（原開盤 brief 晚 {late} 分鐘）"
    # expired / wrong-session must never render a user-facing brief.
    return _ON_TIME_TITLE


def _strip_legacy_wrapper(message: str) -> str:
    """Remove a legacy ``<b>title</b>`` header and ``下次 brief`` footer."""
    body = message
    if body.startswith("<b>") and "</b>" in body:
        body = body.split("</b>", 1)[1].lstrip("\n")
    marker = "\n\n<i>下次 brief:"
    if marker in body:
        body = body.split(marker, 1)[0]
    return body


def render_us_open_message(body: str, decision: UsOpenDecision) -> str:
    """Wrap a freshly generated body with an SLA-aware, honest header.

    ``body`` is produced by regenerating the brief at execution time, so the
    market snapshot always reflects when the workflow actually ran — a late run
    never reuses an open-time snapshot (contract section 5).
    """
    title = us_open_title(decision.status, decision.lateness_minutes)
    late = decision.lateness_minutes or 0
    session = decision.session

    open_note = (
        "美股正式開盤 夏令 21:30／冬令 22:30（台北）；"
        "正式收盤 夏令翌日 04:00／冬令翌日 05:00"
    )
    if decision.status in (STATUS_LATE, STATUS_INTRADAY_RECOVERY):
        timing = (
            f"<i>市場時間基準：{open_note}。"
            f"本 brief 較開盤晚約 {late} 分鐘發送，"
            f"內容已依實際發送時間重新計算市場狀態。</i>"
        )
    else:
        timing = f"<i>市場時間基準：{open_note}。</i>"

    expected = ""
    if session is not None:
        expected = (
            f"<i>本場開盤（台北）：{session.open_at_taipei.strftime('%Y-%m-%d %H:%M')}"
            f"（{'夏令' if session.is_dst else '冬令'}）</i>\n"
        )

    inner = _strip_legacy_wrapper(body)
    footer = "\n\n<i>下次 brief: 美股盤中 brief（夏令翌日 01:00／冬令翌日 02:00）</i>"
    return f"<b>{title}</b>\n{timing}\n{expected}\n{inner}{footer}"
