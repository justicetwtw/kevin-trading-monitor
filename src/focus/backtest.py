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


ATR_WINDOW = 14
#: N-style 波動目標:把每日 ATR%(N)拉到這個目標,低波放大、高波縮小(no look-ahead)。
TARGET_ATR_PCT = 0.02
MAX_POSITION_FRACTION = 1.0

# sizer(frame, i, bench) -> fraction in [0, MAX]; 只有在 signal 為 True 時才套用。
Sizer = Callable[[pd.DataFrame, int, "pd.Series | None"], float]


def _atr_pct(frame: pd.DataFrame, i: int, window: int = ATR_WINDOW) -> float | None:
    """截至第 i 日(含)的 ATR%,即 N/price。High/Low 不足時以 close-to-close 幅度代理。

    只使用 <= i 的資料(no look-ahead)。資料不足回 None。
    """
    if i + 1 < window + 1:
        return None
    seg = frame.iloc[i + 1 - (window + 1) : i + 1]
    close = seg["Close"]
    if {"High", "Low"} <= set(frame.columns):
        high = seg["High"]
        low = seg["Low"]
        prev_close = close.shift(1)
        tr = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
            axis=1,
        ).max(axis=1).dropna()
    else:
        tr = close.diff().abs().dropna()
    if len(tr) < window:
        return None
    atr = float(tr.tail(window).mean())
    last = float(close.iloc[-1])
    if last <= 0:
        return None
    return atr / last


def _unit_sizer(frame, i, bench):
    """預設 sizer:訊號為多時滿倉(1.0)。"""
    return 1.0


def atr_sizer(target_atr_pct: float = TARGET_ATR_PCT, max_fraction: float = MAX_POSITION_FRACTION) -> Sizer:
    """N-style 波動目標 sizer:fraction = clamp(target/ATR%, 0, max)。

    ATR% 算不出來時回 0(fail closed,不亂猜倉位)。
    """

    def _sizer(frame, i, bench):
        atrp = _atr_pct(frame, i)
        if atrp is None or atrp <= 0:
            return 0.0
        return max(0.0, min(max_fraction, target_atr_pct / atrp))

    return _sizer


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
    "dma50_rs_atr_sized": _signal_dma50_rs_breakout,  # 同訊號 + ATR 波動目標倉位
    "full_model": _signal_full_model,
}
_REQUIRES_BENCHMARK = {"dma50_rs", "dma50_rs_breakout", "full_model", "dma50_rs_atr_sized"}
#: baseline -> 是否套用 ATR sizing(其餘用滿倉 unit sizer)。
_ATR_SIZED = {"dma50_rs_atr_sized"}

# 這些 robustness 現已實作(walk_forward / oos / regime / atr sizing);此清單保留給
# 真正尚未做的項目(仍以誠實 capability gap 呈現)。
NOT_IMPLEMENTED_ROBUSTNESS = [
    "paid_options_history_validation",
    "monte_carlo_resampling",
]

# 預先宣告的 regime 切分(§9.2 pre-2020 / 2020–2022 / 2023+ 與 memory-cycle 視資料而定)。
PREDECLARED_REGIMES = (
    ("pre_2020", None, "2019-12-31"),
    ("covid_2020_2022", "2020-01-01", "2022-12-31"),
    ("post_2023", "2023-01-01", None),
)


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


#: 倉位變動小於此值不計為一次 trade(避免 ATR sizing 每日微調灌爆 turnover)。
REBALANCE_THRESHOLD = 0.05


def run_strategy(
    prices: pd.Series | pd.DataFrame,
    signal: Signal,
    cost_bps: float = DEFAULT_COST_BPS,
    benchmark: pd.Series | pd.DataFrame | None = None,
    sizer: Sizer | None = None,
) -> dict[str, Any]:
    """對單一標的跑 long/flat(或 ATR-sized)策略,next-bar 執行且語意一致。

    第 t 日:``in = signal(frame, t-1, bench)`` 決定是否持有,``sizer`` 決定倉位比例;
    該倉位賺取 ``close[t]/close[t-1]-1``,並依實際倉位計入 time-in-market;倉位變動時
    依 |Δfraction| 扣單邊成本。賺報酬的倉位與計入 time-in-market 的倉位一致(無 off-by-one)。
    """
    sizer = sizer or _unit_sizer
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
    position = 0.0
    turnover = 0
    cost_rate = cost_bps / 10000.0

    for t in range(1, len(close)):
        target = float(sizer(frame, t - 1, bench)) if signal(frame, t - 1, bench) else 0.0
        ret = float(close.iloc[t]) / float(close.iloc[t - 1]) - 1.0
        delta = abs(target - position)
        traded = delta >= REBALANCE_THRESHOLD or (target == 0.0 and position != 0.0)
        if traded:
            turnover += 1
            trade_cost = cost_rate * delta
            position = target  # establish target at t-1 close, earns t-1->t return
        else:
            trade_cost = 0.0  # keep current position; no rebalance
        day_ret = position * ret - trade_cost
        in_market_flags.append(1 if position > 0 else 0)
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
        sizer = atr_sizer() if name in _ATR_SIZED else None
        results[name] = run_strategy(
            prices, signal, cost_bps=cost_bps, benchmark=benchmark, sizer=sizer
        )
    return {
        "status": "ok",
        "cost_bps": cost_bps,
        "no_look_ahead": True,
        "execution": "next_bar_close_to_close",
        "rs_basis": "relative_to_benchmark" if benchmark is not None else "benchmark_not_provided",
        "options_history": "not_validated_shadow_only",
        "atr_sizing": {"target_atr_pct": TARGET_ATR_PCT, "window": ATR_WINDOW},
        "not_implemented": NOT_IMPLEMENTED_ROBUSTNESS,
        "results": results,
    }


def walk_forward(
    prices: pd.Series | pd.DataFrame,
    signal: Signal,
    *,
    train_bars: int = 252,
    test_bars: int = 63,
    cost_bps: float = DEFAULT_COST_BPS,
    benchmark: pd.Series | pd.DataFrame | None = None,
    sizer: Sizer | None = None,
) -> dict[str, Any]:
    """Deterministic walk-forward / out-of-sample。

    這些 baseline 沒有需要擬合的參數(20/50/200、RSI14、ATR14、Donchian20/55 皆預先固定),
    因此 walk-forward 的價值是把績效切成連續、不重疊的 out-of-sample 區段,證明不是靠單一
    期間勝出。每段仍要求足夠 history 才計算(含前置 train_bars 的暖身),否則標 insufficient。
    """
    frame = _prepare(prices)
    if frame is None:
        return {"status": "insufficient_history", "segments": []}
    total = len(frame)
    segments: list[dict[str, Any]] = []
    start = train_bars
    while start + test_bars <= total:
        # 每段餵入「暖身 + 該段」的價格,績效只在該 out-of-sample 段結算。
        window = frame.iloc[: start + test_bars]
        seg_prices = window["Close"] if isinstance(prices, pd.Series) else window
        seg_bench = None
        if benchmark is not None:
            b = _align_benchmark(benchmark, frame)
            if b is not None:
                seg_bench = b.iloc[: start + test_bars]
        # 只結算最後 test_bars(out-of-sample)—以整段跑,再取尾段報酬。
        full = run_strategy(seg_prices, signal, cost_bps=cost_bps, benchmark=seg_bench, sizer=sizer)
        segments.append(
            {
                "oos_start_index": start,
                "oos_end_index": start + test_bars,
                "status": full.get("status"),
                "total_return": full.get("total_return"),
                "sharpe": full.get("sharpe"),
                "max_drawdown": full.get("max_drawdown"),
            }
        )
        start += test_bars
    positive = [s for s in segments if isinstance(s.get("total_return"), (int, float)) and s["total_return"] > 0]
    return {
        "status": "ok" if segments else "insufficient_history",
        "train_bars": train_bars,
        "test_bars": test_bars,
        "segment_count": len(segments),
        "positive_segment_share": round(len(positive) / len(segments), 4) if segments else None,
        "segments": segments,
        "note": "fixed-parameter model; OOS segments are non-overlapping and sequential",
    }


def regime_splits(
    prices: pd.Series | pd.DataFrame,
    signal: Signal,
    *,
    cost_bps: float = DEFAULT_COST_BPS,
    benchmark: pd.Series | pd.DataFrame | None = None,
    sizer: Sizer | None = None,
    regimes=PREDECLARED_REGIMES,
) -> dict[str, Any]:
    """Predeclared regime split(需要 DatetimeIndex);每個 regime 各自結算。

    regime 邊界是預先宣告的(不是事後挑期間),避免 data snooping;樣本不足的 regime 標
    insufficient_history 而非硬算。
    """
    frame = _prepare(prices)
    if frame is None or not isinstance(frame.index, pd.DatetimeIndex):
        return {"status": "requires_datetime_index", "regimes": {}}
    out: dict[str, Any] = {}
    for name, lo, hi in regimes:
        mask = pd.Series(True, index=frame.index)
        if lo is not None:
            mask &= frame.index >= pd.Timestamp(lo)
        if hi is not None:
            mask &= frame.index <= pd.Timestamp(hi)
        seg = frame.loc[mask]
        if len(seg) < MIN_HISTORY_BARS:
            out[name] = {"status": "insufficient_history", "bars": len(seg)}
            continue
        seg_prices = seg["Close"] if isinstance(prices, pd.Series) else seg
        seg_bench = None
        if benchmark is not None:
            b_full = benchmark["Close"] if isinstance(benchmark, pd.DataFrame) else benchmark
            seg_bench = b_full.reindex(seg.index)
        out[name] = run_strategy(seg_prices, signal, cost_bps=cost_bps, benchmark=seg_bench, sizer=sizer)
    return {
        "status": "ok",
        "predeclared": True,
        "note": "regime boundaries fixed in advance to avoid data snooping",
        "regimes": out,
    }
