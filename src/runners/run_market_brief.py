"""每日 market brief runner。

`BRIEF_TYPE` identifiers are retained for compatibility. User-facing copy is
normalized through the Taiwan-first market clock so a dispatch time is never
presented as the exchange opening/closing time.
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytz
from loguru import logger

from src.alerts.brief_generator import VALID_BRIEF_TYPES, BriefGenerator
from src.alerts.telegram_bot import send_telegram
from src.config.market_clock import normalize_market_brief_copy
from src.config.settings import TIMEZONE_USER

US_EASTERN = pytz.timezone("America/New_York")
DEDUP_PATH = Path("data_store/brief_sent_today.json")
SILENT_BRIEF_TYPES = {"us_eod", "us_midday"}


def _migrate_dedup_keys(state: dict) -> dict:
    """Migrate historical key names without losing send history."""
    for brief_marks in state.values():
        if not isinstance(brief_marks, dict):
            continue
        if "tw_eod" in brief_marks:
            existing = brief_marks.get("tw_close", False)
            brief_marks["tw_close"] = bool(existing) or bool(
                brief_marks.pop("tw_eod")
            )
    return state


def _load_dedup() -> dict:
    if not DEDUP_PATH.exists():
        return {}
    try:
        data = json.loads(DEDUP_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return _migrate_dedup_keys(data)


def is_already_sent_today(brief_type: str) -> bool:
    data = _load_dedup()
    today_taipei = datetime.now(TIMEZONE_USER).strftime("%Y-%m-%d")
    return data.get(today_taipei, {}).get(brief_type, False)


def mark_sent(brief_type: str) -> None:
    today_taipei = datetime.now(TIMEZONE_USER).strftime("%Y-%m-%d")
    data = _load_dedup()
    if today_taipei not in data:
        data[today_taipei] = {}
    data[today_taipei][brief_type] = True

    cutoff = datetime.now(TIMEZONE_USER).date() - timedelta(days=7)
    data = {
        key: value
        for key, value in data.items()
        if datetime.strptime(key, "%Y-%m-%d").date() >= cutoff
    }

    DEDUP_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEDUP_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def get_market_state() -> dict:
    """Return the current U.S. regular-session phase for diagnostics only."""
    now_et = datetime.now(US_EASTERN)
    is_dst = now_et.dst().total_seconds() > 0
    market_open = now_et.replace(
        hour=9, minute=30, second=0, microsecond=0
    )
    market_close = now_et.replace(
        hour=16, minute=0, second=0, microsecond=0
    )

    if now_et < market_open:
        return {
            "phase": "premarket",
            "minutes_to_open": (market_open - now_et).total_seconds() / 60,
            "is_dst": is_dst,
            "et_time": now_et.strftime("%H:%M ET"),
        }
    if now_et < market_close:
        return {
            "phase": "intraday",
            "minutes_into_session": (
                now_et - market_open
            ).total_seconds()
            / 60,
            "is_dst": is_dst,
            "et_time": now_et.strftime("%H:%M ET"),
        }
    return {
        "phase": "afterhours",
        "minutes_after_close": (
            now_et - market_close
        ).total_seconds()
        / 60,
        "is_dst": is_dst,
        "et_time": now_et.strftime("%H:%M ET"),
    }


def is_silent(brief_type: str) -> bool:
    return brief_type in SILENT_BRIEF_TYPES


def main() -> int:
    brief_type = os.getenv("BRIEF_TYPE", "us_eod")
    if brief_type not in VALID_BRIEF_TYPES:
        logger.error(
            f"Invalid BRIEF_TYPE: {brief_type} "
            f"(valid: {sorted(VALID_BRIEF_TYPES)})"
        )
        return 1

    if is_already_sent_today(brief_type):
        logger.info(f"Brief {brief_type} already sent today, skip (dedup)")
        return 0

    market = get_market_state()
    silent = is_silent(brief_type)
    logger.info(
        f"=== run_market_brief start "
        f"(brief_type={brief_type}, market_phase={market['phase']}, "
        f"dst={market['is_dst']}, silent={silent}) ==="
    )

    try:
        legacy_message = BriefGenerator(brief_type).generate()
        message = normalize_market_brief_copy(legacy_message, brief_type)
    except Exception as exc:
        logger.error(f"brief generation crashed: {exc}")
        return 1

    success = send_telegram(
        message,
        parse_mode="HTML",
        disable_notification=silent,
    )
    if not success:
        logger.error(f"Brief {brief_type} send failed")
        return 1

    mark_sent(brief_type)
    logger.info(
        f"=== run_market_brief done (brief_type={brief_type}, "
        f"silent={silent}, marked) ==="
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
