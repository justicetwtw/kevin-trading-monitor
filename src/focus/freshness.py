"""Source / as-of / freshness helpers(docs/focus_trading_engine_v1.md §5, §13)。

統一計算 security / benchmark / volatility 資料的 as-of 與 stale 狀態,讓 stale /
partial / unavailable 能一致地擋掉 add-ready(fail closed)。

status:
  - "fresh"      :as_of 在 max_age_days 內。
  - "stale"      :as_of 超過 max_age_days(含長假的日曆天)。
  - "missing"    :沒有 as_of 或無資料。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

MAX_PRICE_AGE_DAYS = 5
MAX_VOL_AGE_DAYS = 5


def parse_as_of(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def frame_as_of(frame: Any) -> str | None:
    """回傳 DataFrame 最後一根 bar 的 as-of 字串;無法判定回 None。"""
    if frame is None or getattr(frame, "empty", True):
        return None
    try:
        last = frame.index[-1]
    except (IndexError, TypeError):
        return None
    if hasattr(last, "isoformat"):
        return last.isoformat()
    return str(last)


def freshness(
    as_of: Any,
    reference_date: date | None,
    max_age_days: int = MAX_PRICE_AGE_DAYS,
) -> dict[str, Any]:
    """計算 {as_of, age_days, status, max_age_days}。

    reference_date 為 None 時只能判定 missing / present(不算 age),status 給 "unknown_age"。
    """
    as_of_date = parse_as_of(as_of)
    if as_of_date is None:
        return {"as_of": None, "age_days": None, "status": "missing", "max_age_days": max_age_days}
    if reference_date is None:
        return {
            "as_of": as_of_date.isoformat(),
            "age_days": None,
            "status": "unknown_age",
            "max_age_days": max_age_days,
        }
    age = (reference_date - as_of_date).days
    status = "stale" if age > max_age_days else "fresh"
    return {
        "as_of": as_of_date.isoformat(),
        "age_days": age,
        "status": status,
        "max_age_days": max_age_days,
    }


def is_frame_fresh(frame: Any, reference_date: date | None, max_age_days: int = MAX_PRICE_AGE_DAYS) -> bool:
    """DataFrame 是否存在且 as-of 新鮮(fail closed:缺 as_of / stale 皆回 False)。"""
    if frame is None or getattr(frame, "empty", True):
        return False
    result = freshness(frame_as_of(frame), reference_date, max_age_days)
    return result["status"] == "fresh"
