"""Backtest harness tests(驗收 #9)。"""

import numpy as np
import pandas as pd

from src.focus.backtest import (
    BASELINE_SIGNALS,
    MIN_HISTORY_BARS,
    run_baselines,
    run_strategy,
    _signal_dma50,
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


def test_not_implemented_robustness_is_honest():
    out = run_baselines(_uptrend())
    assert "walk_forward" in out["not_implemented"]
    assert "atr_position_sizing" in out["not_implemented"]
