"""Backtest harness tests(驗收 #9)。"""

import numpy as np
import pandas as pd

from src.focus.backtest import (
    BASELINE_SIGNALS,
    MIN_HISTORY_BARS,
    atr_sizer,
    regime_splits,
    run_baselines,
    run_strategy,
    walk_forward,
    _atr_pct,
    _signal_dma50,
    _signal_dma50_rs,
)


def _uptrend(n=300, start=10.0, end=40.0):
    return pd.Series(np.linspace(start, end, n))


def _choppy(n=300):
    rng = np.arange(n)
    return pd.Series(20 + 3 * np.sin(rng / 5.0))


def test_insufficient_history_flagged_not_computed():
    short = pd.Series(np.linspace(10, 12, 50))
    out = run_baselines(short)
    assert out["status"] == "insufficient_history"
    assert out["bars"] == 50


def test_baselines_all_present():
    out = run_baselines(_uptrend())
    assert out["status"] == "ok"
    assert set(out["results"]) == set(BASELINE_SIGNALS)
    assert out["no_look_ahead"] is True
    assert out["execution"] == "next_bar_close_to_close"


def test_buy_and_hold_matches_price_return_on_uptrend():
    prices = _uptrend(n=300, start=10.0, end=40.0)
    out = run_strategy(prices, BASELINE_SIGNALS["buy_and_hold"], cost_bps=0.0)
    # 10 -> 40 is +300%; buy&hold with zero cost should be close
    assert out["total_return"] > 2.9


def test_costs_reduce_return_vs_zero_cost():
    prices = _choppy()
    cheap = run_strategy(prices, _signal_dma50, cost_bps=0.0)
    pricey = run_strategy(prices, _signal_dma50, cost_bps=50.0)
    # More trading friction cannot improve the result on the same path
    assert pricey["total_return"] <= cheap["total_return"]
    assert pricey["trade_count"] == cheap["trade_count"]


def test_no_look_ahead_signal_uses_prior_bar():
    # Construct a series where the last bar jumps up. A look-ahead strategy would
    # capture that jump; next-bar execution must NOT, because the position for
    # the jump day is decided from the pre-jump close.
    closes = [100.0] * 260 + [200.0]
    prices = pd.Series(closes)
    out = run_strategy(prices, BASELINE_SIGNALS["dma50_only"], cost_bps=0.0)
    # The +100% final bar cannot be captured: on the flat run price==sma so the
    # dma50 filter is not long into the jump. Return stays modest, not ~+100%.
    assert out["total_return"] < 0.5


def test_time_in_market_between_zero_and_one():
    out = run_strategy(_uptrend(), BASELINE_SIGNALS["dma50_only"])
    assert 0.0 <= out["time_in_market"] <= 1.0


def test_metrics_shape_complete():
    out = run_strategy(_uptrend(), BASELINE_SIGNALS["full_model"])
    for key in ("total_return", "cagr", "max_drawdown", "sharpe", "sortino", "calmar", "trade_count"):
        assert key in out


def test_min_history_constant_covers_200dma():
    assert MIN_HISTORY_BARS > 200


def test_rs_baselines_require_benchmark():
    # Without a benchmark, RS baselines must NOT silently use self-momentum.
    out = run_baselines(_uptrend(), benchmark=None)
    for name in ("dma50_rs", "dma50_rs_breakout", "full_model"):
        assert out["results"][name]["status"] == "benchmark_required"
    assert out["rs_basis"] == "benchmark_not_provided"


def test_rs_baselines_run_with_benchmark():
    prices = _uptrend(n=300, start=10.0, end=40.0)
    weaker_bench = _uptrend(n=300, start=10.0, end=15.0)  # symbol outperforms
    out = run_baselines(prices, benchmark=weaker_bench)
    assert out["rs_basis"] == "relative_to_benchmark"
    assert out["results"]["dma50_rs"]["status"] == "ok"
    # downside_capture is computed only when a benchmark is present
    assert "downside_capture" in out["results"]["dma50_rs"]


def test_execution_time_in_market_consistent():
    # time_in_market must reflect the positions that actually earn the returns.
    out = run_strategy(_uptrend(), BASELINE_SIGNALS["buy_and_hold"], cost_bps=0.0)
    # buy-and-hold is long every day after the first → time_in_market == 1.0
    assert out["time_in_market"] == 1.0


def test_not_implemented_lists_only_genuinely_missing():
    # walk-forward / OOS / regime / ATR sizing are now implemented and must NOT
    # be listed as not_implemented; only genuinely-missing items remain.
    out = run_baselines(_uptrend())
    assert "walk_forward" not in out["not_implemented"]
    assert "atr_position_sizing" not in out["not_implemented"]
    assert "regime_split" not in out["not_implemented"]
    assert "paid_options_history_validation" in out["not_implemented"]
    assert out["atr_sizing"]["target_atr_pct"] > 0


def _frame_hl(n=400, start=10.0, end=40.0, seed=1):
    idx = pd.date_range("2019-06-03", periods=n, freq="B")
    c = np.linspace(start, end, n)
    return pd.DataFrame(
        {"Close": c, "High": c * 1.01, "Low": c * 0.99, "Volume": [1e6] * n}, index=idx
    )


def test_atr_pct_scales_and_sizer_inverse_to_vol():
    calm = _frame_hl()
    # atr% is positive and the sizer yields a fraction in [0, 1]
    atrp = _atr_pct(calm, len(calm) - 1)
    assert atrp is not None and atrp > 0
    frac = atr_sizer()(calm, len(calm) - 1, None)
    assert 0.0 <= frac <= 1.0


def test_atr_sizer_bigger_when_lower_vol():
    low_vol = _frame_hl(end=13.0)   # gentle slope → low ATR%
    high_vol = _frame_hl(end=80.0)  # steep slope → high ATR%
    f_low = atr_sizer()(low_vol, len(low_vol) - 1, None)
    f_high = atr_sizer()(high_vol, len(high_vol) - 1, None)
    assert f_low >= f_high


def test_atr_sized_baseline_runs_with_benchmark():
    prices = _frame_hl(n=400, start=10.0, end=40.0)
    bench = pd.Series(np.linspace(10, 15, 400), index=prices.index)
    out = run_baselines(prices, benchmark=bench)
    assert out["results"]["dma50_rs_atr_sized"]["status"] == "ok"


def test_walk_forward_segments_non_overlapping():
    prices = _frame_hl(n=600)
    bench = pd.Series(np.linspace(10, 15, 600), index=prices.index)
    wf = walk_forward(prices, _signal_dma50_rs, benchmark=bench, train_bars=252, test_bars=63)
    assert wf["status"] == "ok"
    assert wf["segment_count"] >= 1
    ends = [s["oos_end_index"] for s in wf["segments"]]
    starts = [s["oos_start_index"] for s in wf["segments"]]
    # each OOS window advances by test_bars → strictly increasing, non-overlapping
    assert starts == sorted(starts)
    assert all(b - a == 63 for a, b in zip(starts, ends))


def test_regime_splits_predeclared_and_insufficient_marked():
    prices = _frame_hl(n=1300, start=10, end=50)  # spans 2019->~2024
    out = regime_splits(prices, _signal_dma50)
    assert out["predeclared"] is True
    assert set(out["regimes"]) == {"pre_2020", "covid_2020_2022", "post_2023"}
    # regimes with < MIN_HISTORY_BARS are marked, not force-computed
    for name, res in out["regimes"].items():
        assert res["status"] in {"ok", "insufficient_history"}


def test_regime_splits_requires_datetime_index():
    out = regime_splits(pd.Series(np.linspace(10, 40, 300)), _signal_dma50)
    assert out["status"] == "requires_datetime_index"


def test_walk_forward_oos_isolated_from_pre_window_returns():
    # Changing returns strictly before the OOS window must NOT change that
    # window's metrics (proves OOS-only accounting, not whole-prefix).
    base = _frame_hl(n=600)
    perturbed = base.copy()
    perturbed.iloc[:200, perturbed.columns.get_loc("Close")] = np.linspace(3, 6, 200)
    wf_base = walk_forward(base, _signal_dma50, train_bars=252, test_bars=63)
    wf_pert = walk_forward(perturbed, _signal_dma50, train_bars=252, test_bars=63)
    # last segment is well after the perturbed region
    assert wf_base["segments"][-1]["total_return"] == wf_pert["segments"][-1]["total_return"]


def test_walk_forward_rs_trades_with_benchmark():
    prices = _frame_hl(n=600, start=10, end=40)      # strong up
    bench = pd.Series(np.linspace(10, 13, 600), index=prices.index)  # weaker
    wf = walk_forward(prices, _signal_dma50_rs, benchmark=bench, train_bars=252, test_bars=63)
    # benchmark alignment preserved → RS actually takes exposure in OOS segments
    assert any((s.get("time_in_market") or 0) > 0 for s in wf["segments"])
    assert wf["oos_aggregate"]["oos_bars"] > 0


def test_trade_level_metrics_distinct_from_daily():
    out = run_strategy(_choppy(), _signal_dma50, cost_bps=0.0)
    # both families present and named honestly
    for k in ("daily_hit_rate", "avg_daily_win", "avg_daily_loss",
              "trade_hit_rate", "avg_trade_win", "avg_trade_loss", "closed_trade_count"):
        assert k in out
    # closed trades are runs of in-market days, not rebalance events
    assert out["closed_trade_count"] <= out["trade_count"] + 1


def _controlled_frame(closes):
    n = len(closes)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"Close": closes, "High": [c * 1.01 for c in closes],
         "Low": [c * 0.99 for c in closes], "Volume": [1e6] * n},
        index=idx,
    )


def test_trade_ledger_includes_exit_cost():
    # finding P1: the exit-bar transaction cost must be attributed to the trade
    # being closed. With cost > 0 the single closed trade's return must be lower.
    n = 260
    closes = [100.0] * n
    for i in range(120, 140):
        closes[i] = 100.0 + (i - 119)   # rise while held
    for i in range(140, n):
        closes[i] = 120.0

    def sig(frame, i, bench):
        return 118 <= i < 145           # one long window, then exit

    frame = _controlled_frame(closes)
    free = run_strategy(frame, sig, cost_bps=0.0)
    costly = run_strategy(frame, sig, cost_bps=50.0)
    assert free["closed_trade_count"] == 1
    assert costly["closed_trade_count"] == 1
    # entry + exit costs strictly reduce the single closed trade's return
    assert costly["closed_trades"][0] < free["closed_trades"][0]


def test_open_terminal_trade_not_counted_as_closed():
    # finding P1: a position still open at the end of the sample is an OPEN
    # terminal trade, never counted inside closed_trade_count.
    n = 260
    closes = list(np.linspace(100.0, 130.0, n))

    def sig(frame, i, bench):
        return i >= 150                 # enters and never exits before sample end

    out = run_strategy(_controlled_frame(closes), sig, cost_bps=0.0)
    assert out["has_open_terminal_trade"] is True
    assert out["open_terminal_trade"] is not None
    assert out["closed_trade_count"] == 0
    assert out["closed_trades"] == []


def test_carry_in_trade_excluded_from_closed_stats():
    # finding P1 round 5: a position opened before the OOS window (carry-in) that
    # exits inside the window is recorded as carry-in, NOT a clean closed trade.
    n = 300
    closes = list(np.linspace(100.0, 130.0, n))

    def sig(frame, i, bench):
        return i < 200                  # long from the start, exits mid-sample

    out = run_strategy(_controlled_frame(closes), sig, cost_bps=0.0, metrics_start_index=150)
    assert out["carry_in_trade_count"] == 1
    assert out["closed_trade_count"] == 0   # carry-in trade is excluded from clean stats


def test_walk_forward_spanning_trade_not_double_counted_as_closed():
    # finding P1 round 5: a single continuous long position spanning multiple OOS
    # windows must not be booked as a clean closed trade in each window; every
    # window sees it as carry-in and/or carry-out, so clean closed_trade_count is 0.
    prices = _frame_hl(n=700)           # continuous uptrend → dma50 stays long
    wf = walk_forward(prices, _signal_dma50, train_bars=252, test_bars=63)
    assert wf["segment_count"] >= 2
    total_clean_closed = sum((s.get("closed_trade_count") or 0) for s in wf["segments"])
    assert total_clean_closed == 0
    # and at least one window carries the position across its boundary
    assert any(s.get("has_open_terminal_trade") or (s.get("carry_in_trade_count") or 0) > 0
               for s in wf["segments"])
