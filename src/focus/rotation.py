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
from src.focus.universe import (
    BENCHMARK_BROAD,
    BENCHMARK_SEMI,
    THEME_CONSTITUENTS,
)

ROTATION_WINDOWS = (5, 20, 63)
#: rank/percentile 需要的最低有效成員覆蓋率;不足即拒絕排名(不給假名次)。
MIN_MEMBER_COVERAGE = 0.6


def _valid_members(frames: dict[str, pd.DataFrame], symbols: list[str], reference_date=None) -> list[str]:
    """回傳有價量、且(給定 reference_date 時)未 stale 的成員。"""
    from src.focus.freshness import is_frame_fresh

    out: list[str] = []
    for sym in symbols:
        frame = frames.get(sym)
        if frame is None or getattr(frame, "empty", True) or "Close" not in frame:
            continue
        if reference_date is not None and not is_frame_fresh(frame, reference_date):
            continue
        out.append(sym)
    return out


def _basket_close(
    frames: dict[str, pd.DataFrame],
    symbols: list[str],
    reference_date=None,
    min_members: int = 2,
) -> pd.Series | None:
    """合成 theme basket 收盤序列:先「依日期對齊」到共同交易日,再在共同起點 rebase
    等權平均。避免 later-listed / 短史成員因各自 rebase 而扭曲權重與跨期比較。

    stale 成員(給 reference_date 時)先剔除;有效成員 < ``min_members`` 或無共同交易日回
    None。單一成分 theme(configured==1)可傳 min_members=1 做「明示的 single-name proxy」。
    """
    cols: list[pd.Series] = []
    for sym in _valid_members(frames, symbols, reference_date):
        close = frames[sym]["Close"].dropna()
        if not close.empty:
            cols.append(close.rename(sym))
    if len(cols) < max(1, min_members):
        return None
    combined = pd.concat(cols, axis=1).dropna()  # align on common trading dates first
    if combined.empty or len(combined) < 2:
        return None
    first = combined.iloc[0]
    if (first == 0).any():
        return None
    rebased = combined / first  # rebase at the common aligned start → truly equal-weight
    return rebased.mean(axis=1)


def _align_two(a: pd.Series | None, b: pd.Series | None) -> tuple[pd.Series | None, pd.Series | None]:
    """把兩條序列依日期對齊到共同 index(供 RS 端點對齊);任一為 None 回 (None, None)。"""
    if a is None or b is None:
        return None, None
    joined = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
    if joined.empty or len(joined) < 2:
        return None, None
    return joined["a"], joined["b"]


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
    reference_date=None,
) -> dict[str, Any]:
    """單一 theme 的輪動 proxy row。

    basket 只用 THEME_CONSTITUENTS(單一成分股),不混入該 theme 的 ETF proxy;
    stale 成員先剔除,依日期對齊後在共同起點 rebase;coverage 不足時拒絕 rank/percentile。
    """
    from src.focus.freshness import frame_as_of, freshness

    symbols = THEME_CONSTITUENTS.get(theme, [])
    configured = len(symbols)
    valid = _valid_members(member_frames, symbols, reference_date)
    coverage = round(len(valid) / configured, 4) if configured else None
    # 單一成分 theme(如 memory_hbm_dram=[MU]):允許明示的 single-name proxy,
    # 不再永遠 insufficient_data;>1 成分維持等權 basket(至少 2 有效成員)。
    single_name = configured == 1
    basket = _basket_close(
        member_frames, symbols, reference_date=reference_date,
        min_members=1 if single_name else 2,
    )
    basket_kind = "single_name_proxy" if single_name else "equal_weight_basket"

    # Coverage / freshness gate:成員覆蓋不足或無 basket → 拒絕給 RS/rank(不假裝當前)。
    if basket is None or coverage is None or coverage < MIN_MEMBER_COVERAGE:
        return {
            "theme": theme,
            "status": "insufficient_coverage" if basket is not None else "insufficient_data",
            "metric_kind": "price_return_proxy",
            "basket_kind": basket_kind,
            "member_count": configured,
            "valid_member_count": len(valid),
            "member_coverage": coverage,
            "as_of": frame_as_of(basket) if basket is not None else None,
        }

    basket_as_of = frame_as_of(basket)
    qqq = benchmark_frames.get(BENCHMARK_BROAD)
    smh = benchmark_frames.get(BENCHMARK_SEMI)
    qqq_close = qqq["Close"].dropna() if qqq is not None and "Close" in qqq else None
    smh_close = smh["Close"].dropna() if smh is not None and "Close" in smh else None

    # RS:先把 basket 與 benchmark 依「日期」對齊端點,再算相對強度(避免 positional 錯期)。
    basket_q, qqq_a = _align_two(basket, qqq_close)
    basket_s, smh_a = _align_two(basket, smh_close)

    returns = {f"return_{w}d": _period_return(basket, w) for w in ROTATION_WINDOWS}
    rs_qqq_20 = relative_strength(basket_q, qqq_a, 20)
    rs_qqq_63 = relative_strength(basket_q, qqq_a, 63)
    rs_smh = relative_strength(basket_s, smh_a, 20)

    # leadership acceleration proxy:RS20 - RS63(vs QQQ),兩者都可得才計算。
    if rs_qqq_20.get("value") is not None and rs_qqq_63.get("value") is not None:
        rs_acceleration = round(rs_qqq_20["value"] - rs_qqq_63["value"], 6)
    else:
        rs_acceleration = None

    # breakout share:**只用**與 basket 相同的 fresh valid 成員(finding P1 修正:
    # stale 成員不得再污染 breakout/breadth),20D 與 55D 分開,並公開分母。
    from src.focus.trend import donchian_state

    def _breakout_share(window: int) -> tuple[float | None, int]:
        up = 0
        counted = 0
        for sym in valid:
            frame = member_frames.get(sym)
            if frame is None or getattr(frame, "empty", True):
                continue
            state = donchian_state(frame, window)
            if state.get("status") == "insufficient_data":
                continue
            counted += 1
            if state.get("status") == "breakout_up":
                up += 1
        return (round(up / counted, 4) if counted else None), counted

    breakout_20d_share, breakout_20d_counted = _breakout_share(20)
    breakout_55d_share, breakout_55d_counted = _breakout_share(55)

    # leadership 方向:RS20 相對 RS63 加速(>0)或惡化(<0)。
    if rs_acceleration is None:
        leadership_direction = "unknown"
    elif rs_acceleration > 0:
        leadership_direction = "accelerating"
    elif rs_acceleration < 0:
        leadership_direction = "deteriorating"
    else:
        leadership_direction = "flat"

    # breadth:**只用** fresh valid 成員中價格在各自 20/50/200DMA 之上的比例,並公開分母。
    breadth: dict[str, float | None] = {}
    breadth_counted: dict[str, int] = {}
    for window in (20, 50, 200):
        above = 0
        counted = 0
        for sym in valid:
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
        breadth_counted[f"above_sma_{window}"] = counted

    return {
        "theme": theme,
        "status": "ok",
        "metric_kind": "price_return_proxy",
        "basket_kind": basket_kind,
        "member_count": configured,
        "valid_member_count": len(valid),
        "member_coverage": coverage,
        "as_of": basket_as_of,
        **returns,
        "rs_vs_qqq_20": rs_qqq_20.get("value"),
        "rs_vs_qqq_63": rs_qqq_63.get("value"),
        "rs_vs_smh_20": rs_smh.get("value"),
        "rs_acceleration": rs_acceleration,
        "leadership_direction": leadership_direction,
        "breakout_20d_share": breakout_20d_share,
        "breakout_20d_counted": breakout_20d_counted,
        "breakout_55d_share": breakout_55d_share,
        "breakout_55d_counted": breakout_55d_counted,
        "breadth": breadth,
        "breadth_counted": breadth_counted,
        # theme_percentile_rank 由 panel 跨 theme 計算後補上(見 build_rotation_panel)。
    }


def build_rotation_panel(
    member_frames: dict[str, pd.DataFrame],
    benchmark_frames: dict[str, pd.DataFrame],
    reference_date=None,
) -> dict[str, Any]:
    """所有 theme 的輪動 panel(依 20D RS vs QQQ 排序,None 排最後)。"""
    rows = [
        theme_rotation_row(theme, member_frames, benchmark_frames, reference_date=reference_date)
        for theme in THEME_CONSTITUENTS
    ]

    # 跨 theme percentile / rank(依 RS20 vs QQQ);只有算得出 RS 的 theme 參與排名,
    # 缺 RS 的 theme percentile/rank 為 None(不硬給名次)。
    ranked = [r for r in rows if isinstance(r.get("rs_vs_qqq_20"), (int, float))]
    ranked.sort(key=lambda r: r["rs_vs_qqq_20"], reverse=True)
    n = len(ranked)
    for position, row in enumerate(ranked):
        row["theme_rank"] = position + 1
        row["theme_count_ranked"] = n
        # percentile:最強=1.0,最弱→接近 0(n=1 時給 1.0)。
        row["theme_percentile_rank"] = round(1.0 - position / (n - 1), 4) if n > 1 else 1.0
    for row in rows:
        if "theme_percentile_rank" not in row:
            row["theme_percentile_rank"] = None
            row["theme_rank"] = None

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
