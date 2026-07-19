"""Theme rotation / leadership proxy(docs/focus_trading_engine_v1.md §5 Layer C)。

重要紅線(§5 Layer C 結尾):
- 沒有穩定 ETF fund-flow source 時,名稱必須是 "rotation/leadership proxy",
  不得宣稱真實 fund flow。本模組輸出一律標 ``metric_kind = "price_return_proxy"``。
- 缺資料的 theme 回 status="insufficient_data",不用 0 補。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.focus.trend import relative_strength
from src.focus.universe import BENCHMARK_BROAD, BENCHMARK_SEMI, THEME_GROUPS

ROTATION_WINDOWS = (5, 20, 63)


def _basket_close(frames: dict[str, pd.DataFrame], symbols: list[str]) -> pd.Series | None:
    """把一組 symbol 的收盤標準化後等權平均,合成 theme basket 收盤序列。

    每個成員先除以自身首值(rebase=1.0),對齊索引後取平均;
    有效成員 < 2 或無共同索引回 None。
    """
    series: list[pd.Series] = []
    for sym in symbols:
        frame = frames.get(sym)
        if frame is None or getattr(frame, "empty", True) or "Close" not in frame:
            continue
        close = frame["Close"].dropna()
        if close.empty or float(close.iloc[0]) == 0:
            continue
        series.append(close / float(close.iloc[0]))
    if len(series) < 2:
        return None
    combined = pd.concat(series, axis=1).dropna()
    if combined.empty or len(combined) < 2:
        return None
    return combined.mean(axis=1)


def _period_return(close: pd.Series, lookback: int) -> float | None:
    if close is None or len(close) < lookback + 1:
        return None
    start = float(close.iloc[-1 - lookback])
    if start == 0:
        return None
    return round(float(close.iloc[-1]) / start - 1.0, 6)


def theme_rotation_row(
    theme: str,
    member_frames: dict[str, pd.DataFrame],
    benchmark_frames: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    """單一 theme 的輪動 proxy row。"""
    symbols = THEME_GROUPS.get(theme, [])
    basket = _basket_close(member_frames, symbols)
    if basket is None:
        return {
            "theme": theme,
            "status": "insufficient_data",
            "metric_kind": "price_return_proxy",
            "member_count": len(symbols),
        }

    qqq = benchmark_frames.get(BENCHMARK_BROAD)
    smh = benchmark_frames.get(BENCHMARK_SEMI)
    qqq_close = qqq["Close"].dropna() if qqq is not None and "Close" in qqq else None
    smh_close = smh["Close"].dropna() if smh is not None and "Close" in smh else None

    returns = {f"return_{w}d": _period_return(basket, w) for w in ROTATION_WINDOWS}
    rs_qqq = relative_strength(basket, qqq_close, 20)
    rs_smh = relative_strength(basket, smh_close, 20)

    # breadth:成員中價格在各自 20/50/200DMA 之上的比例。
    breadth: dict[str, float | None] = {}
    for window in (20, 50, 200):
        above = 0
        counted = 0
        for sym in symbols:
            frame = member_frames.get(sym)
            if frame is None or getattr(frame, "empty", True) or "Close" not in frame:
                continue
            close = frame["Close"].dropna()
            if len(close) < window:
                continue
            counted += 1
            if float(close.iloc[-1]) > float(close.tail(window).mean()):
                above += 1
        breadth[f"above_sma_{window}"] = (
            round(above / counted, 4) if counted else None
        )

    return {
        "theme": theme,
        "status": "ok",
        "metric_kind": "price_return_proxy",
        "member_count": len(symbols),
        **returns,
        "rs_vs_qqq_20": rs_qqq.get("value"),
        "rs_vs_smh_20": rs_smh.get("value"),
        "breadth": breadth,
    }


def build_rotation_panel(
    member_frames: dict[str, pd.DataFrame],
    benchmark_frames: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    """所有 theme 的輪動 panel(依 20D RS vs QQQ 排序,None 排最後)。"""
    rows = [
        theme_rotation_row(theme, member_frames, benchmark_frames)
        for theme in THEME_GROUPS
        if theme != "portfolio_hedge"
    ]
    rows.sort(
        key=lambda row: (
            row.get("rs_vs_qqq_20") is None,
            -(row.get("rs_vs_qqq_20") or 0.0),
            row["theme"],
        )
    )
    return {
        "metric_kind": "price_return_proxy",
        "disclaimer": (
            "Leadership/rotation proxy from delayed price returns only. "
            "Not real fund flow, dealer positioning or confirmed accumulation."
        ),
        "rows": rows,
    }
