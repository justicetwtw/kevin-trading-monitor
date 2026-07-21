"""Focus trend / RS deterministic tests(驗收 #3, #4)。"""

import numpy as np
import pandas as pd

from src.focus.trend import (
    atr,
    bollinger,
    compute_trend_frame,
    donchian_state,
    relative_strength,
    rsi,
    sma,
    sma_slope,
)


def _frame(closes, highs=None, lows=None, volumes=None):
    n = len(closes)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "Close": closes,
            "High": highs if highs is not None else [c * 1.01 for c in closes],
            "Low": lows if lows is not None else [c * 0.99 for c in closes],
            "Volume": volumes if volumes is not None else [1_000_000] * n,
        },
        index=idx,
    )


def test_sma_matches_manual_mean():
    closes = list(range(1, 61))  # 1..60
    frame = _frame(closes)
    assert sma(frame["Close"], 50) == float(np.mean(closes[-50:]))


def test_sma_slope_sign_up_and_down():
    up = pd.Series(np.linspace(10, 30, 80))
    down = pd.Series(np.linspace(30, 10, 80))
    assert sma_slope(up, 50) > 0
    assert sma_slope(down, 50) < 0


def test_sma_insufficient_returns_none():
    assert sma(pd.Series([1, 2, 3]), 50) is None


def test_rsi_all_gains_is_high():
    closes = pd.Series(np.linspace(10, 40, 60))
    value = rsi(closes)
    assert value is not None and value > 90


def test_rsi_all_losses_is_low():
    closes = pd.Series(np.linspace(40, 10, 60))
    value = rsi(closes)
    assert value is not None and value < 10


def test_bollinger_pct_b_within_bounds():
    closes = pd.Series(np.linspace(10, 20, 40))
    bb = bollinger(closes)
    assert 0.0 <= bb["pct_b"] <= 1.5
    assert bb["upper"] > bb["mid"] > bb["lower"]


def test_atr_positive_on_ranged_data():
    frame = _frame(list(np.linspace(10, 20, 40)))
    value = atr(frame)
    assert value is not None and value > 0


def test_donchian_breakout_up_no_lookahead():
    # 20 flat bars then a jump: last close should break the prior-20-day high,
    # and the channel high must NOT include the breakout bar itself.
    closes = [100.0] * 25 + [130.0]
    frame = _frame(closes, highs=[100.0] * 25 + [130.0], lows=[100.0] * 26)
    state = donchian_state(frame, 20)
    assert state["status"] == "breakout_up"
    assert state["channel_high"] == 100.0  # excludes the current breakout bar


def test_donchian_insufficient_data():
    frame = _frame([100.0] * 5)
    assert donchian_state(frame, 20)["status"] == "insufficient_data"


def test_relative_strength_outperformer_positive():
    strong = pd.Series(np.linspace(10, 20, 80))   # +100%
    weak = pd.Series(np.linspace(10, 12, 80))      # +20%
    rs = relative_strength(strong, weak, 63)
    assert rs["status"] == "ok"
    assert rs["value"] > 0


def test_relative_strength_missing_benchmark_is_honest_none():
    strong = pd.Series(np.linspace(10, 20, 80))
    rs = relative_strength(strong, None, 63)
    assert rs["value"] is None
    assert rs["status"] == "benchmark_unavailable"


def test_relative_strength_short_benchmark_unavailable():
    strong = pd.Series(np.linspace(10, 20, 80))
    short_bench = pd.Series([10, 11, 12])
    rs = relative_strength(strong, short_bench, 63)
    assert rs["status"] == "benchmark_unavailable"


def test_compute_trend_frame_full_shape():
    closes = list(np.linspace(10, 40, 260))
    frame = _frame(closes)
    bench = _frame(list(np.linspace(10, 20, 260)))
    out = compute_trend_frame(frame, benchmark_frames={"QQQ": bench, "SMH": bench})
    assert out["status"] == "ok"
    assert out["sma"][50] is not None
    assert out["rs_vs_qqq"][63]["status"] == "ok"
    assert out["rs_vs_theme"][20]["status"] == "benchmark_unavailable"


def test_compute_trend_frame_empty_insufficient():
    out = compute_trend_frame(pd.DataFrame())
    assert out["status"] == "insufficient_data"
