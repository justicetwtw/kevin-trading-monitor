"""Price / trend / RS backtest harness(docs/focus_trading_engine_v1.md §9)。

目的:讓 50DMA / RS / breakout 曝險過濾器可回測,並與固定 baselines 比較。
完整 options 歷史回測在付費歷史資料核准前一律標 shadow / not_validated,不在此偽造。

嚴守(含 review round-1 修正):
  - No look-ahead:第 t 日的部位由「截至 t-1 收盤」的訊號決定,並賺取 t-1→t 的報酬;
    賺取該報酬的部位就是被計入 time-in-market 的部位(執行語意一致,無 off-by-one)。
  - RS 是相對 benchmark(QQQ/SMH)的強度,不是單一股票自身動能;需要 benchmark 序列,
    未提供 benchmark 的 RS baseline 明確標 ``benchmark_required``,不用自身動能冒充。
  - Adjusted prices:呼叫方須傳入還原權息後的收盤。
  - Transaction cost:曝險變動時扣單邊成本(bps)。
  - 樣本不足以固定 window 計算時,標 insufficient_history。
  - 尚未實作的 robustness(walk-forward、out-of-sample、regime split)與部分 metrics
    明確列在 not_implemented,不宣稱 acceptance 已完成。

Baselines(§9.1):
  buy_and_hold / dma50_only / dma50_momentum(自身動能,誠實命名)/
  dma50_rs / dma50_rs_breakout / full_model(後三者需 benchmark)。
"""

from __future__ import annotations

import math
from typing import Any, Callable

import pandas as pd

MIN_HISTORY_BARS = 220  # 需 >200 才有 200DMA + 緩衝
DEFAULT_COST_BPS = 5.0  # 每次曝險變動的單邊成本(基點)

# signal(frame, i, bench) -> bool；i 為決策日索引(用截至 i 的資訊)。
Signal = Callable[[pd.DataFrame, int, "pd.Series | None"], bool]


def _prepare(prices: pd.Series | pd.DataFrame) -> pd.DataFrame | None:
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


def _align_benchmark(prices, frame: pd.DataFrame) -> pd.Series | None:
    """把 benchmark 對齊到 frame 的索引,回傳 reset 後的 Close 序列;無法對齊回 None。"""
    if prices is None:
        return None
    if isinstance(prices, pd.DataFrame):
        if "Close" not in prices:
            return None
        bench = prices["Close"]
    elif isinstance(prices, pd.Series):
        bench = prices
    else:
        return None
    aligned = bench.reindex(frame.index)
    if aligned.isna().any():
        return None
    return aligned.reset_index(drop=True)


def _sma(frame: pd.DataFrame, i: int, window: int) -> float | None:
    if i + 1 < window:
        return None
    return float(frame["Close"].iloc[i + 1 - window : i + 1].mean())


def _self_momentum(frame: pd.DataFrame, i: int, window: int = 63) -> bool:
    if i < window:
        return False
    return float(frame["Close"].iloc[i]) > float(frame["Close"].iloc[i - window])


def _rs_vs_bench(frame: pd.DataFrame, i: int, bench: pd.Series | None, window: int = 63) -> float | None:
    """symbol 期間報酬 − benchmark 期間報酬。benchmark 缺或長度不足回 None。"""
    if bench is None or i < window:
        return None
    c = frame["Close"]
    if float(c.iloc[i - window]) == 0 or float(bench.iloc[i - window]) == 0:
        return None
    sym = float(c.iloc[i]) / float(c.iloc[i - window]) - 1.0
    b = float(bench.iloc[i]) / float(bench.iloc[i - window]) - 1.0
    return sym - b


def _donchian_breakout(frame: pd.DataFrame, i: int, window: int = 20) -> bool:
    if i < window:
        return False
    prior_high = float(frame["Close"].iloc[i - window : i].max())
    return float(frame["Close"].iloc[i]) > prior_high


# ---- baseline signals ----

def _signal_buy_and_hold(frame, i, bench):
    return True


def _signal_dma50(frame, i, bench):
    sma50 = _sma(frame, i, 50)
    return sma50 is not None and float(frame["Close"].iloc[i]) > sma50


def _signal_dma50_momentum(frame, i, bench):
    return _signal_dma50(frame, i, bench) and _self_momentum(frame, i)


def _signal_dma50_rs(frame, i, bench):
    rs = _rs_vs_bench(frame, i, bench)
    return _signal_dma50(frame, i, bench) and rs is not None and rs > 0


def _signal_dma50_rs_breakout(frame, i, bench):
    return _signal_dma50_rs(frame, i, bench) and _donchian_breakout(frame, i)


def _signal_full_model(frame, i, bench):
    if not _signal_dma50_rs(frame, i, bench):
        return False
    sma50_now = _sma(frame, i, 50)
    sma50_prev = _sma(frame, i - 10, 50) if i >= 10 else None
    rising_50 = sma50_now is not None and sma50_prev is not None and sma50_now >= sma50_prev
    return _donchian_breakout(frame, i) or rising_50


#: baseline -> (signal, requires_benchmark)
BASELINE_SIGNALS: dict[str, Signal] = {
    "buy_and_hold": _signal_buy_and_hold,
    "dma50_only": _signal_dma50,
    "dma50_momentum": _signal_dma50_momentum,
    "dma50_rs": _signal_dma50_rs,
    "dma50_rs_breakout": _signal_dma50_rs_breakout,
    "full_model": _signal_full_model,
}
_REQUIRES_BENCHMARK = {"dma50_rs", "dma50_rs_breakout", "full_model"}

NOT_IMPLEMENTED_ROBUSTNESS = [
    "walk_forward",
    "out_of_sample_split",
    "regime_split",
    "atr_position_sizing",
]


def _recovery_bars(equity: list[float]) -> int | None:
    """從 max-drawdown 谷底回到「谷底前高點」所需 bar 數;尚未回復回 None，無回撤回 0。"""
    peak = equity[0]
    max_dd = 0.0
    trough_idx = 0
    for idx, value in enumerate(equity):
        peak = max(peak, value)
        dd = value / peak - 1.0 if peak > 0 else 0.0
        if dd < max_dd:
            max_dd = dd
            trough_idx = idx
    if max_dd == 0.0:
        return 0
    prior_peak = max(equity[: trough_idx + 1])
    for idx in range(trough_idx, len(equity)):
        if equity[idx] >= prior_peak:
            return idx - trough_idx
    return None


def _metrics(
    equity: list[float],
    strat_returns: list[float],
    in_market_flags: list[int],
    bench_returns: list[float] | None,
    turnover: int,
) -> dict[str, Any]:
    if len(equity) < 2:
        return {"status": "insufficient_history"}
    total_return = equity[-1] / equity[0] - 1.0
    n = len(strat_returns)
    years = n / 252.0 if n else 0.0
    cagr = (equity[-1] / equity[0]) ** (1 / years) - 1.0 if years > 0 and equity[0] > 0 else None

    peak = equity[0]
    max_dd = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            max_dd = min(max_dd, value / peak - 1.0)

    mean = sum(strat_returns) / n if n else 0.0
    var = sum((r - mean) ** 2 for r in strat_returns) / (n - 1) if n > 1 else 0.0
    std = math.sqrt(var)
    sharpe = (mean / std * math.sqrt(252)) if std > 0 else None

    downside = [r for r in strat_returns if r < 0]
    if downside:
        d_std = math.sqrt(sum(r * r for r in downside) / len(downside))
        sortino = (mean / d_std * math.sqrt(252)) if d_std > 0 else None
    else:
        sortino = None

    calmar = (cagr / abs(max_dd)) if (cagr is not None and max_dd < 0) else None

    # in-market 日的命中率與盈虧比(以日報酬為口徑,已與 time-in-market 對齊)。
    in_market_returns = [r for r, flag in zip(strat_returns, in_market_flags) if flag]
    wins = [r for r in in_market_returns if r > 0]
    losses = [r for r in in_market_returns if r < 0]
    hit_rate = round(len(wins) / len(in_market_returns), 4) if in_market_returns else None
    avg_win = round(sum(wins) / len(wins), 6) if wins else None
    avg_loss = round(sum(losses) / len(losses), 6) if losses else None
    days_in_market = sum(in_market_flags)

    downside_capture = None
    if bench_returns is not None and len(bench_returns) == n:
        bench_down = [(s, b) for s, b in zip(strat_returns, bench_returns) if b < 0]
        bench_down_sum = sum(b for _, b in bench_down)
        strat_on_down = sum(s for s, _ in bench_down)
        if bench_down_sum != 0:
            downside_capture = round(strat_on_down / bench_down_sum, 4)

    return {
        "status": "ok",
        "total_return": round(total_return, 6),
        "cagr": round(cagr, 6) if cagr is not None else None,
        "max_drawdown": round(max_dd, 6),
        "sharpe": round(sharpe, 4) if sharpe is not None else None,
        "sortino": round(sortino, 4) if sortino is not None else None,
        "calmar": round(calmar, 4) if calmar is not None else None,
        "time_in_market": round(days_in_market / n, 4) if n else 0.0,
        "trade_count": turnover,
        "hit_rate": hit_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "downside_capture": downside_capture,
        "recovery_bars": _recovery_bars(equity),
        "bars": n,
    }


def run_strategy(
    prices: pd.Series | pd.DataFrame,
    signal: Signal,
    cost_bps: float = DEFAULT_COST_BPS,
    benchmark: pd.Series | pd.DataFrame | None = None,
) -> dict[str, Any]:
    """對單一標的跑 long/flat 策略,next-bar 執行且執行語意一致。

    第 t 日:``desired = signal(frame, t-1, bench)`` 決定 t 日部位;該部位賺取
    ``close[t]/close[t-1]-1``,並被計入 time-in-market;若相對前一日部位改變,
    在該日扣單邊成本。賺報酬的部位與計入 time-in-market 的部位一致(無 off-by-one)。
    """
    frame = _prepare(prices)
    if frame is None or len(frame) < MIN_HISTORY_BARS:
        return {"status": "insufficient_history", "bars": 0 if frame is None else len(frame)}

    bench = _align_benchmark(benchmark, frame)
    frame = frame.reset_index(drop=True)
    close = frame["Close"]

    equity = [1.0]
    strat_returns: list[float] = []
    bench_returns: list[float] | None = [] if bench is not None else None
    in_market_flags: list[int] = []
    position = 0
    turnover = 0
    cost = cost_bps / 10000.0

    for t in range(1, len(close)):
        desired = 1 if signal(frame, t - 1, bench) else 0
        ret = float(close.iloc[t]) / float(close.iloc[t - 1]) - 1.0
        traded = desired != position
        day_ret = desired * ret - (cost if traded else 0.0)
        if traded:
            turnover += 1
        position = desired
        in_market_flags.append(position)
        strat_returns.append(day_ret)
        if bench_returns is not None:
            bench_returns.append(
                float(bench.iloc[t]) / float(bench.iloc[t - 1]) - 1.0
            )
        equity.append(equity[-1] * (1.0 + day_ret))

    result = _metrics(equity, strat_returns, in_market_flags, bench_returns, turnover)
    result["equity_final"] = round(equity[-1], 6)
    return result


def run_baselines(
    prices: pd.Series | pd.DataFrame,
    cost_bps: float = DEFAULT_COST_BPS,
    benchmark: pd.Series | pd.DataFrame | None = None,
) -> dict[str, Any]:
    """跑全部 baseline 並回傳比較表。

    需要 benchmark 的 RS baseline 在未提供 benchmark 時標 ``benchmark_required``,
    不用自身動能冒充 RS。樣本不足時整體標 insufficient_history。
    """
    frame = _prepare(prices)
    if frame is None or len(frame) < MIN_HISTORY_BARS:
        return {
            "status": "insufficient_history",
            "min_history_bars": MIN_HISTORY_BARS,
            "bars": 0 if frame is None else len(frame),
            "note": "not enough adjusted history to fix 20/50/200 windows",
        }
    results: dict[str, Any] = {}
    for name, signal in BASELINE_SIGNALS.items():
        if name in _REQUIRES_BENCHMARK and benchmark is None:
            results[name] = {"status": "benchmark_required"}
            continue
        results[name] = run_strategy(prices, signal, cost_bps=cost_bps, benchmark=benchmark)
    return {
        "status": "ok",
        "cost_bps": cost_bps,
        "no_look_ahead": True,
        "execution": "next_bar_close_to_close",
        "rs_basis": "relative_to_benchmark" if benchmark is not None else "benchmark_not_provided",
        "options_history": "not_validated_shadow_only",
        "not_implemented": NOT_IMPLEMENTED_ROBUSTNESS,
        "results": results,
    }
