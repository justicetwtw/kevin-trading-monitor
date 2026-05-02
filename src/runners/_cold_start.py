"""冷啟動保護 — 首次跑(seen 為空)時,只放行 N 小時內的 items。

Trump 鏡像 32k 則歷史貼文 / RSS 跨日 lookback 失效 / SEC 模組層 lookback 改動 都靠這層擋。
與模組層 lookback 並存(defense in depth);非冷啟動模式直接放行所有 items。
"""

from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from loguru import logger


def _default_seen_empty(seen) -> bool:
    if seen is None:
        return True
    try:
        return len(seen) == 0
    except TypeError:
        return False


def _to_aware_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def filter_with_cold_start_protection(
    items: list,
    seen_set,
    get_created_at: Callable,
    cold_start_window_hours: int = 24,
    seen_is_empty_check: Optional[Callable] = None,
) -> tuple[list, list]:
    """冷啟動保護:首次跑只放行 cold_start_window_hours 內的 items,舊 items 標 seen 不推。

    Returns:
      (items_to_process, items_to_mark_seen_only)

    冷啟動偵測:seen_is_empty_check(seen) is True → 進入冷啟動模式。
    時間比對統一 UTC;get_created_at 拿到 naive datetime 視為 UTC。
    get_created_at 回 None 的 item 在冷啟動模式視為「無時間 → 標 seen 不推」(保守)。
    """
    is_empty_fn = seen_is_empty_check or _default_seen_empty
    is_cold = is_empty_fn(seen_set)

    if not is_cold:
        return list(items or []), []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=cold_start_window_hours)
    to_process: list = []
    to_mark: list = []

    for item in items or []:
        try:
            ts = get_created_at(item)
        except Exception as e:
            logger.warning(f"cold_start get_created_at raised: {e}; treating as old")
            to_mark.append(item)
            continue
        ts_utc = _to_aware_utc(ts)
        if ts_utc is None or ts_utc < cutoff:
            to_mark.append(item)
        else:
            to_process.append(item)

    logger.warning(
        f"Cold start: marking {len(to_mark)} old items as seen, "
        f"processing {len(to_process)} recent items "
        f"(window={cold_start_window_hours}h)"
    )
    return to_process, to_mark
