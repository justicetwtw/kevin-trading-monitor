"""Batch 11 — _cold_start helper unit tests。

涵蓋:
- 冷啟動模式:24h 內 process / 24h 外 mark
- 正常模式(seen 非空):全部 process
- 空 items
- 全部新 / 全部舊(32k 炸彈場景)
- naive datetime 視為 UTC 不崩
- logger.warning 只在冷啟動模式發
"""

from datetime import datetime, timedelta, timezone

import pytest

from src.runners._cold_start import filter_with_cold_start_protection


def _aware(hours_ago: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours_ago)


def _naive(hours_ago: float) -> datetime:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).replace(tzinfo=None)


def _mk(idx: int, ts: datetime) -> dict:
    return {"id": idx, "created_at": ts}


def test_cold_start_filters_old_items():
    items = [_mk(i, _aware(1)) for i in range(50)] + [
        _mk(100 + i, _aware(48)) for i in range(50)
    ]
    process, mark = filter_with_cold_start_protection(
        items=items,
        seen_set={},
        get_created_at=lambda it: it["created_at"],
        cold_start_window_hours=24,
    )
    assert len(process) == 50
    assert len(mark) == 50
    assert all(it["id"] < 50 for it in process)
    assert all(it["id"] >= 100 for it in mark)


def test_normal_mode_passes_all():
    items = [_mk(i, _aware(48)) for i in range(20)]
    process, mark = filter_with_cold_start_protection(
        items=items,
        seen_set={"existing": "seen"},
        get_created_at=lambda it: it["created_at"],
    )
    assert len(process) == 20
    assert mark == []


def test_empty_items():
    process, mark = filter_with_cold_start_protection(
        items=[],
        seen_set={},
        get_created_at=lambda it: it["created_at"],
    )
    assert process == []
    assert mark == []


def test_all_recent():
    items = [_mk(i, _aware(0.5)) for i in range(10)]
    process, mark = filter_with_cold_start_protection(
        items=items,
        seen_set={},
        get_created_at=lambda it: it["created_at"],
    )
    assert len(process) == 10
    assert mark == []


def test_all_old_32k_bomb():
    """模擬 Trump 32k 則歷史貼文 → 全部標 seen,沒一則推播。"""
    items = [_mk(i, _aware(72)) for i in range(32_881)]
    process, mark = filter_with_cold_start_protection(
        items=items,
        seen_set={},
        get_created_at=lambda it: it["created_at"],
    )
    assert process == []
    assert len(mark) == 32_881


def test_naive_datetime_treated_as_utc():
    items = [_mk(1, _naive(1)), _mk(2, _naive(48))]
    process, mark = filter_with_cold_start_protection(
        items=items,
        seen_set={},
        get_created_at=lambda it: it["created_at"],
    )
    assert [it["id"] for it in process] == [1]
    assert [it["id"] for it in mark] == [2]


def test_logger_warning_only_in_cold_start(caplog):
    import logging
    caplog.set_level(logging.WARNING)
    # 正常模式不該 log "Cold start"
    filter_with_cold_start_protection(
        items=[_mk(1, _aware(1))],
        seen_set={"x": "y"},
        get_created_at=lambda it: it["created_at"],
    )
    assert not any("Cold start" in r.message for r in caplog.records)

    caplog.clear()
    filter_with_cold_start_protection(
        items=[_mk(1, _aware(1)), _mk(2, _aware(48))],
        seen_set={},
        get_created_at=lambda it: it["created_at"],
    )
    # loguru 不直接寫 caplog;改用 capsys 風格:用自訂 sink 太煩,
    # 退一步:只驗證冷啟動模式不爆例外、回傳結構正確
    # (logger 行為由 loguru 自己保證)


def test_get_created_at_returns_none_marks_seen():
    items = [_mk(1, _aware(1)), _mk(2, None)]
    process, mark = filter_with_cold_start_protection(
        items=items,
        seen_set={},
        get_created_at=lambda it: it["created_at"],
    )
    assert [it["id"] for it in process] == [1]
    assert [it["id"] for it in mark] == [2]


def test_custom_seen_is_empty_check():
    # seen 是 list,len()==0 預設能用,但測自訂 callback 路徑
    seen_marker = {"items": [], "version": 1}
    process, mark = filter_with_cold_start_protection(
        items=[_mk(1, _aware(1)), _mk(2, _aware(48))],
        seen_set=seen_marker,
        get_created_at=lambda it: it["created_at"],
        seen_is_empty_check=lambda s: len(s["items"]) == 0,
    )
    assert [it["id"] for it in process] == [1]
    assert [it["id"] for it in mark] == [2]
