"""Price / trend / RS backtest harness(docs/focus_trading_engine_v1.md §9)。

目的:讓 50DMA / RS / breakout 曝險過濾器可回測,並與固定 baselines 比較。
完整 options 歷史回測在付費歷史資料核准前一律標 shadow / not_validated,不在此偽造。

嚴守:
  - No look-ahead:訊號用「截至前一日收盤」計算,部位在「下一日」才生效(next-bar)。
  - Adjusted prices:呼叫方須傳入還原權息後的收盤(auto_adjust)。
  - Transaction cost:曝險變動時扣 per-turn 成本(bps)。
  - 樣本不足以固定 window 計算時,標 insufficient_history,不硬算。

Baselines(§9.1):
  buy_and_hold / dma50_only / dma50_rs / dma50_rs_breakout_atr / full_model
"""

from __future__ import annotations

import math
from typing import Any, Callable

import pandas as pd

MIN_HISTORY_BARS = 220  # 需 >200 才有 200DMA + 緩衝
DEFAULT_COST_BPS = 5.0  # 每次曝險變動的單邊成本(基點)

Signal = Callable[[pd.DataFrame, int], bool]


def _prepare(prices: pd.Series | pd.DataFrame) -> pd.DataFrame | None:
    """整理成含 Close(+可選 High/Low)的 DataFrame;不足回 None。"""
    if isinstance(prices, pd.Series):
        frame = prices.to_frame("Close")
    elif isinstance(prices, pd.DataFrame) and "Close" in prices:
        frame = prices.copy()
    else:
        return None
    frame = frame.dropna(subset=["Close"])
    if len(frame) < 2:
        return None
    return frame


def _signal_buy_and_hold(frame: pd.DataFrame, i: int) -> bool:
    return True


def _sma(frame: pd.DataFrame, i: int, window: int) -> float | None:
    """截至第 i 日(含)的 SMA;不足回 None。i 為 signal 計算日索引。"""
    if i + 1 < window:
        return None
    return float(frame["Close"].iloc[i + 1 - window : i + 1].mean())


def _signal_dma50(frame: pd.DataFrame, i: int) -> bool:
    sma50 = _sma(frame, i, 50)
    if sma50 is None:
        return False
    return float(frame["Close"].iloc[i]) > sma50


def _rs_positive(frame: pd.DataFrame, i: int, window: int = 63) -> bool:
    """相對自身 window 前的動能為正(單標的 backtest 用自身動能代 RS proxy)。"""
    if i < window:
        return False
    return float(frame["Close"].iloc[i]) > float(frame["Close"].iloc[i - window])


def _signal_dma50_rs(frame: pd.DataFrame, i: int) -> bool:
    return _signal_dma50(frame, i) and _rs_positive(frame, i)


def _donchian_breakout(frame: pd.DataFrame, i: int, window: int = 20) -> bool:
    """第 i 日收盤突破前 window 日(不含當日)高點。"""
    if i < window:
        return False
    prior_high = float(frame["Close"].iloc[i - window : i].max())
    return float(frame["Close"].iloc[i]) > prior_high


def _signal_dma50_rs_breakout(frame: pd.DataFrame, i: int) -> bool:
    return _signal_dma50_rs(frame, i) and _donchian_breakout(frame, i)


def _signal_full_model(frame: pd.DataFrame, i: int) -> bool:
    """Full available model:50DMA 之上 + RS 正 +(突破 or 站穩上升 50DMA)。

    不含未取得的 options history(§9.1 明示排除)。
    """
    if not _signal_dma50_rs(frame, i):
        return False
    sma50_now = _sma(frame, i, 50)
    sma50_prev = _sma(frame, i - 10, 50) if i >= 10 else None
    rising_50 = (
        sma50_now is not None and sma50_prev is not None and sma50_now >= sma50_prev
    )
    return _donchian_breakout(frame, i) or rising_50


BASELINE_SIGNALS: dict[str, Signal] = {
    "buy_and_hold": _signal_buy_and_hold,
    "dma50_only": _signal_dma50,
    "dma50_rs": _signal_dma50_rs,
    "dma50_rs_breakout_atr": _signal_dma50_rs_breakout,
    "full_model": _signal_full_model,
}


def _metrics(equity: list[float], daily_returns: list[float], time_in_market: float, turnover: int) -> dict[str, Any]:
    if len(equity) < 2:
        return {"status": "insufficient_history"}
    total_return = equity[-1] / equity[0] - 1.0
    n = len(daily_returns)
    years = n / 252.0 if n else 0.0
    cagr = (equity[-1] / equity[0]) ** (1 / years) - 1.0 if years > 0 and equity[0] > 0 else None

    peak = equity[0]
    max_dd = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            max_dd = min(max_dd, value / peak - 1.0)

    mean = sum(daily_returns) / n if n else 0.0
    var = sum((r - mean) ** 2 for r in daily_returns) / (n - 1) if n > 1 else 0.0
    std = math.sqrt(var)
    sharpe = (mean / std * math.sqrt(252)) if std > 0 else None

    downside = [r for r in daily_returns if r < 0]
    if downside:
        d_var = sum(r * r for r in downside) / len(downside)
        d_std = math.sqrt(d_var)
        sortino = (mean / d_std * math.sqrt(252)) if d_std > 0 else None
    else:
        sortino = None

    calmar = (cagr / abs(max_dd)) if (cagr is not None and max_dd < 0) else None

    return {
        "status": "ok",
        "total_return": round(total_return, 6),
        "cagr": round(cagr, 6) if cagr is not None else None,
        "max_drawdown": round(max_dd, 6),
        "sharpe": round(sharpe, 4) if sharpe is not None else None,
        "sortino": round(sortino, 4) if sortino is not None else None,
        "calmar": round(calmar, 4) if calmar is not None else None,
        "time_in_market": round(time_in_market, 4),
        "trade_count": turnover,
        "bars": n,
    }


def run_strategy(
    prices: pd.Series | pd.DataFrame,
    signal: Signal,
    cost_bps: float = DEFAULT_COST_BPS,
) -> dict[str, Any]:
    """對單一標的跑 long/flat 策略。

    No look-ahead 機制:第 t 日用 signal(frame, t-1) 決定第 t 日「持有與否」,
    報酬用第 t-1→t 的價格變化。曝險變動時在該日扣單邊成本。
    """
    frame = _prepare(prices)
    if frame is None or len(frame) < MIN_HISTORY_BARS:
        return {"status": "insufficient_history", "bars": 0 if frame is None else len(frame)}

    close = frame["Close"].reset_index(drop=True)
    frame = frame.reset_index(drop=True)
    equity = [1.0]
    daily_returns: list[float] = []
    position = 0  # 0=flat, 1=long
    days_in_market = 0
    turnover = 0
    cost = cost_bps / 10000.0

    for t in range(1, len(close)):
        # 訊號只看到 t-1 收盤(next-bar 執行)。
        desired = 1 if signal(frame, t - 1) else 0
        ret = float(close.iloc[t]) / float(close.iloc[t - 1]) - 1.0
        day_ret = position * ret
        if desired != position:
            day_ret -= cost  # 進出場單邊成本
            turnover += 1
        position = desired
        days_in_market += position
        daily_returns.append(day_ret)
        equity.append(equity[-1] * (1.0 + day_ret))

    time_in_market = days_in_market / (len(close) - 1) if len(close) > 1 else 0.0
    result = _metrics(equity, daily_returns, time_in_market, turnover)
    result["equity_final"] = round(equity[-1], 6)
    return result


def run_baselines(
    prices: pd.Series | pd.DataFrame,
    cost_bps: float = DEFAULT_COST_BPS,
) -> dict[str, Any]:
    """跑全部 baseline 並回傳比較表。樣本不足時整體標 insufficient_history。"""
    frame = _prepare(prices)
    if frame is None or len(frame) < MIN_HISTORY_BARS:
        return {
            "status": "insufficient_history",
            "min_history_bars": MIN_HISTORY_BARS,
            "bars": 0 if frame is None else len(frame),
            "note": "not enough adjusted history to fix 20/50/200 windows",
        }
    results = {
        name: run_strategy(prices, signal, cost_bps=cost_bps)
        for name, signal in BASELINE_SIGNALS.items()
    }
    return {
        "status": "ok",
        "cost_bps": cost_bps,
        "no_look_ahead": True,
        "execution": "next_bar",
        "options_history": "not_validated_shadow_only",
        "results": results,
    }
