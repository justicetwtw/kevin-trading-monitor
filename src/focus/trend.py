"""Trend / momentum / relative-strength 計算(docs/focus_trading_engine_v1.md §5 Layer C)。

全部用 pandas 純實作,方便 deterministic 測試,並嚴守:

- No look-ahead:Donchian breakout 以「不含當日」的前 N 日高/低判定,close 才是當日確認。
- 資料不足回 None,不用中性值硬補(fail closed)。
- RS 是相對強度比值,benchmark 缺 / stale / 長度不足時回 None + 原因。
- 這些是 timing / 曝險節奏訊號,不是 thesis,也不產生訂單。

固定參數(§9.2,預先固定避免參數挖礦):
    SMA 20 / 50 / 200, RSI 14, BB 20/2σ, ATR 14, Donchian 20 / 55,
    RS 20 / 63 / 126。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

SMA_WINDOWS = (20, 50, 200)
RS_WINDOWS = (20, 63, 126)
DONCHIAN_WINDOWS = (20, 55)
ATR_WINDOW = 14
RSI_WINDOW = 14
BB_WINDOW = 20
BB_STD = 2.0
#: 判定 slope 方向所需的回看天數(20DMA 的近月斜率)。
SLOPE_LOOKBACK = 10


def _close(df: pd.DataFrame) -> pd.Series | None:
    if df is None or getattr(df, "empty", True) or "Close" not in df:
        return None
    close = df["Close"].dropna()
    return close if not close.empty else None


def sma(close: pd.Series, window: int) -> float | None:
    if close is None or len(close) < window:
        return None
    return float(close.tail(window).mean())


def sma_slope(close: pd.Series, window: int, lookback: int = SLOPE_LOOKBACK) -> float | None:
    """回傳 SMA 的近期斜率(每日平均變化 / 目前 SMA,normalized)。

    需要 window + lookback 根資料才有兩個可比較的 SMA 點;不足回 None。
    正值=上升,負值=下降。
    """
    if close is None or len(close) < window + lookback:
        return None
    rolling = close.rolling(window).mean().dropna()
    if len(rolling) <= lookback:
        return None
    latest = float(rolling.iloc[-1])
    prior = float(rolling.iloc[-1 - lookback])
    if latest == 0:
        return None
    return round((latest - prior) / abs(latest) / lookback, 6)


def rsi(close: pd.Series, window: int = RSI_WINDOW) -> float | None:
    """Wilder RSI。資料不足回 None。"""
    if close is None or len(close) < window + 1:
        return None
    delta = close.diff().dropna()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    last_gain = float(avg_gain.iloc[-1])
    last_loss = float(avg_loss.iloc[-1])
    if last_loss == 0:
        return 100.0 if last_gain > 0 else 50.0
    rs = last_gain / last_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 4)


def bollinger(close: pd.Series, window: int = BB_WINDOW, std: float = BB_STD) -> dict[str, Any]:
    """回傳 BB upper/lower/%B/BandWidth。資料不足回 {} 。"""
    if close is None or len(close) < window:
        return {}
    tail = close.tail(window)
    mid = float(tail.mean())
    sd = float(tail.std(ddof=0))
    upper = mid + std * sd
    lower = mid - std * sd
    last = float(close.iloc[-1])
    width = upper - lower
    pct_b = (last - lower) / width if width else 0.5
    bandwidth = width / mid if mid else None
    return {
        "mid": round(mid, 6),
        "upper": round(upper, 6),
        "lower": round(lower, 6),
        "pct_b": round(pct_b, 6),
        "bandwidth": round(bandwidth, 6) if bandwidth is not None else None,
        "touch_lower": bool(last <= lower * 1.005),
        "touch_upper": bool(last >= upper * 0.995),
    }


def atr(df: pd.DataFrame, window: int = ATR_WINDOW) -> float | None:
    """Wilder ATR(需要 High/Low/Close)。資料不足回 None。"""
    if df is None or getattr(df, "empty", True):
        return None
    if not {"High", "Low", "Close"} <= set(df.columns):
        return None
    frame = df[["High", "Low", "Close"]].dropna()
    if len(frame) < window + 1:
        return None
    high = frame["High"]
    low = frame["Low"]
    prev_close = frame["Close"].shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1).dropna()
    if len(true_range) < window:
        return None
    atr_series = true_range.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    return round(float(atr_series.iloc[-1]), 6)


def donchian_state(df: pd.DataFrame, window: int) -> dict[str, Any]:
    """Donchian breakout state,no look-ahead。

    以「不含當日」的前 ``window`` 日 high/low 當通道;當日收盤突破才算 breakout。
    資料不足回 {"status": "insufficient_data"}。
    """
    close = _close(df)
    if close is None or "High" not in df or "Low" not in df:
        return {"status": "insufficient_data", "window": window}
    high = df["High"].dropna()
    low = df["Low"].dropna()
    if len(close) < window + 1 or len(high) < window + 1 or len(low) < window + 1:
        return {"status": "insufficient_data", "window": window}
    # 前 window 日(不含當日):shift(1) 後取最後 window 根。
    prior_high = float(high.shift(1).tail(window).max())
    prior_low = float(low.shift(1).tail(window).min())
    last = float(close.iloc[-1])
    if last > prior_high:
        status = "breakout_up"
    elif last < prior_low:
        status = "breakout_down"
    else:
        status = "inside"
    return {
        "status": status,
        "window": window,
        "channel_high": round(prior_high, 6),
        "channel_low": round(prior_low, 6),
        "close": round(last, 6),
    }


def relative_strength(
    close: pd.Series,
    benchmark_close: pd.Series | None,
    window: int,
) -> dict[str, Any]:
    """RS = symbol 期間報酬 / benchmark 期間報酬(以比值變化衡量)。

    回傳 {value, status}:
      - value>0 代表期間內跑贏 benchmark,<0 代表跑輸。
      - benchmark 缺 / 長度不足 → status="benchmark_unavailable",value=None(不猜)。
    """
    if close is None or len(close) < window + 1:
        return {"value": None, "status": "insufficient_data", "window": window}
    if benchmark_close is None or len(benchmark_close) < window + 1:
        return {"value": None, "status": "benchmark_unavailable", "window": window}
    sym_ret = float(close.iloc[-1]) / float(close.iloc[-1 - window]) - 1.0
    bench_ret = float(benchmark_close.iloc[-1]) / float(benchmark_close.iloc[-1 - window]) - 1.0
    return {
        "value": round(sym_ret - bench_ret, 6),
        "symbol_return": round(sym_ret, 6),
        "benchmark_return": round(bench_ret, 6),
        "status": "ok",
        "window": window,
    }


def volume_percentile(df: pd.DataFrame, lookback: int = 252) -> float | None:
    """最新一日成交量在近 ``lookback`` 日中的百分位(0-1)。不足回 None。"""
    if df is None or getattr(df, "empty", True) or "Volume" not in df:
        return None
    vol = df["Volume"].dropna()
    if len(vol) < 20:
        return None
    window = vol.tail(lookback)
    last = float(vol.iloc[-1])
    rank = float((window < last).sum()) / float(len(window))
    return round(rank, 4)


def compute_trend_frame(
    df: pd.DataFrame,
    benchmark_frames: dict[str, pd.DataFrame] | None = None,
    theme_basket_close: pd.Series | None = None,
) -> dict[str, Any]:
    """把單一 symbol 的價量資料算成完整 trend / RS 特徵包。

    benchmark_frames:{"QQQ": df, "SMH": df};缺席的 benchmark RS 回 unavailable。
    theme_basket_close:該 symbol 所屬 theme 的合成收盤序列(可為 None)。
    """
    close = _close(df)
    if close is None:
        return {"status": "insufficient_data"}

    last = float(close.iloc[-1])
    smas = {n: sma(close, n) for n in SMA_WINDOWS}
    slopes = {n: sma_slope(close, n) for n in SMA_WINDOWS}

    benchmark_frames = benchmark_frames or {}

    def _bench_close(name: str) -> pd.Series | None:
        frame = benchmark_frames.get(name)
        return _close(frame) if frame is not None else None

    rs_qqq = {n: relative_strength(close, _bench_close("QQQ"), n) for n in RS_WINDOWS}
    rs_smh = {n: relative_strength(close, _bench_close("SMH"), n) for n in RS_WINDOWS}
    rs_theme = {n: relative_strength(close, theme_basket_close, n) for n in RS_WINDOWS}

    def _pct_from(sma_val: float | None) -> float | None:
        if sma_val is None or sma_val == 0:
            return None
        return round(last / sma_val - 1.0, 6)

    return {
        "status": "ok",
        "close": round(last, 6),
        "sma": {n: smas[n] for n in SMA_WINDOWS},
        "sma_slope": {n: slopes[n] for n in SMA_WINDOWS},
        "pct_from_sma": {n: _pct_from(smas[n]) for n in SMA_WINDOWS},
        "above_sma": {
            n: (bool(last > smas[n]) if smas[n] is not None else None)
            for n in SMA_WINDOWS
        },
        "rsi": rsi(close),
        "bollinger": bollinger(close),
        "atr": atr(df),
        "donchian": {n: donchian_state(df, n) for n in DONCHIAN_WINDOWS},
        "volume_percentile": volume_percentile(df),
        "rs_vs_qqq": rs_qqq,
        "rs_vs_smh": rs_smh,
        "rs_vs_theme": rs_theme,
    }
