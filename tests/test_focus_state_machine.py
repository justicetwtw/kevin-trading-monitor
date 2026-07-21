"""Thesis / timing / exposure state machine tests(驗收 #1, #2)。

核心驗收 #2:下降 50DMA 之下的 RSI/BB 超賣不得提高 long eligibility。
"""

from src.focus.state_machine import (
    COMPANY_THESIS_STATES,
    EXPOSURE_POSTURES,
    TIMING_STATES,
    classify_timing,
    derive_exposure_posture,
    evaluate_symbol,
)


def _rs_block(value):
    """RS dict for a given 20/63 value (value=None => benchmark unavailable)."""
    if value is None:
        return {w: {"value": None, "status": "benchmark_unavailable"} for w in (20, 63, 126)}
    return {w: {"value": value, "status": "ok"} for w in (20, 63, 126)}


def _trend(
    close,
    sma20,
    sma50,
    sma200,
    slope50,
    slope20=0.01,
    rsi=50.0,
    touch_lower=False,
    touch_upper=False,
    donch20="inside",
    donch55="inside",
    volume_percentile=0.6,
    rs20=0.05,
    rs63=0.03,
    reclaimed=False,
):
    def _rs(v20, v63):
        return {
            20: {"value": v20, "status": "ok" if v20 is not None else "benchmark_unavailable"},
            63: {"value": v63, "status": "ok" if v63 is not None else "benchmark_unavailable"},
            126: {"value": v63, "status": "ok" if v63 is not None else "benchmark_unavailable"},
        }

    return {
        "status": "ok",
        "close": close,
        "sma": {20: sma20, 50: sma50, 200: sma200},
        "sma_slope": {20: slope20, 50: slope50, 200: 0.0},
        "above_sma": {
            20: (close > sma20) if sma20 is not None else None,
            50: (close > sma50) if sma50 is not None else None,
            200: (close > sma200) if sma200 is not None else None,
        },
        "rsi": rsi,
        "bollinger": {
            "pct_b": 0.1 if touch_lower else 0.5,
            "touch_lower": touch_lower,
            "touch_upper": touch_upper,
        },
        "donchian": {
            20: {"status": donch20},
            55: {"status": donch55},
        },
        "reclaim": {"reclaimed": reclaimed, "status": "ok"},
        "volume_percentile": volume_percentile,
        "rs_vs_qqq": _rs(rs20, rs63),
        "rs_vs_smh": _rs(rs20, rs63),
        "rs_vs_theme": _rs(rs20, rs63),
    }


# ---------- 驗收 #2:falling-knife regression ----------

def test_falling_price_below_declining_50dma_is_not_a_buy():
    # price below a DECLINING 50DMA, RSI oversold, riding lower BB band
    trend = _trend(
        close=80.0, sma20=85.0, sma50=95.0, sma200=110.0,
        slope50=-0.02, slope20=-0.02, rsi=22.0, touch_lower=True,
    )
    timing = classify_timing(trend)
    assert timing["state"] == "trend_damaged"
    assert timing["long_entry_eligible"] is False
    assert "falling_knife_oversold_not_a_buy" in timing["flags"]


def test_oversold_does_not_flip_eligibility_vs_neutral():
    # Same declining-50DMA structure; adding oversold RSI must not INCREASE
    # eligibility relative to a non-oversold reading.
    base = _trend(80.0, 85.0, 95.0, 110.0, slope50=-0.02, rsi=45.0)
    oversold = _trend(
        80.0, 85.0, 95.0, 110.0, slope50=-0.02, rsi=20.0, touch_lower=True
    )
    assert classify_timing(base)["long_entry_eligible"] is False
    assert classify_timing(oversold)["long_entry_eligible"] is False


def test_healthy_pullback_above_rising_50dma_is_eligible():
    # RSI 40 + lower-band test but ABOVE a rising 50DMA → healthy, eligible
    trend = _trend(
        close=102.0, sma20=101.0, sma50=98.0, sma200=90.0,
        slope50=0.02, slope20=0.0, rsi=40.0, touch_lower=True,
    )
    timing = classify_timing(trend)
    assert timing["state"] in {"trend_healthy", "pullback_test"}
    assert timing["long_entry_eligible"] is True


def test_below_50dma_flat_slope_is_bottom_watch_not_add():
    trend = _trend(
        close=95.0, sma20=97.0, sma50=100.0, sma200=99.0,
        slope50=0.0, slope20=0.0, rsi=35.0,
    )
    timing = classify_timing(trend)
    assert timing["state"] == "bottom_watch"
    assert timing["long_entry_eligible"] is False


def test_breakout_with_volume_is_eligible():
    trend = _trend(
        close=120.0, sma20=110.0, sma50=105.0, sma200=95.0,
        slope50=0.03, slope20=0.03, rsi=62.0, donch20="breakout_up",
        volume_percentile=0.8,
    )
    timing = classify_timing(trend)
    assert timing["state"] == "breakout_confirmed"
    assert timing["long_entry_eligible"] is True


def test_breakout_low_volume_flags_but_not_eligible():
    trend = _trend(
        close=120.0, sma20=110.0, sma50=105.0, sma200=95.0,
        slope50=0.03, slope20=0.03, rsi=62.0, donch20="breakout_up",
        volume_percentile=0.2,
    )
    timing = classify_timing(trend)
    assert timing["state"] == "breakout_confirmed"
    assert timing["long_entry_eligible"] is False
    assert "breakout_low_volume" in timing["flags"]


def test_overheated_extended_not_eligible():
    trend = _trend(
        close=130.0, sma20=110.0, sma50=105.0, sma200=95.0,
        slope50=0.03, slope20=0.03, rsi=82.0, touch_upper=True,
    )
    timing = classify_timing(trend)
    assert timing["state"] == "overheated"
    assert timing["long_entry_eligible"] is False


def test_healthy_trend_without_rs_is_not_add_eligible():
    # Same healthy structure but RS benchmark unavailable → add gate must close.
    trend = _trend(
        102.0, 101.0, 98.0, 90.0, slope50=0.02, slope20=0.02, rsi=55.0, rs20=None, rs63=None
    )
    timing = classify_timing(trend)
    assert timing["state"] == "trend_healthy"
    assert timing["long_entry_eligible"] is False
    assert "rs_unavailable_add_gate_closed" in timing["flags"]


def test_healthy_trend_with_lagging_rs_is_not_add_eligible():
    # RS present but not leading (negative) → not eligible.
    trend = _trend(
        102.0, 101.0, 98.0, 90.0, slope50=0.02, slope20=0.02, rsi=55.0, rs20=-0.04, rs63=-0.02
    )
    timing = classify_timing(trend)
    assert timing["state"] == "trend_healthy"
    assert timing["long_entry_eligible"] is False
    assert "rs_not_leading_add_gate_closed" in timing["flags"]


def test_reclaim_confirmed_is_reachable():
    trend = _trend(
        100.0, 99.0, 98.0, 95.0, slope50=0.01, slope20=0.01, rsi=55.0,
        rs20=0.05, rs63=0.03, reclaimed=True,
    )
    timing = classify_timing(trend)
    assert timing["state"] == "reclaim_confirmed"
    assert timing["long_entry_eligible"] is True


def test_breakout_volume_none_is_not_confirmed():
    trend = _trend(
        120.0, 110.0, 105.0, 95.0, slope50=0.03, slope20=0.03, rsi=62.0,
        donch20="breakout_up", volume_percentile=None,
    )
    timing = classify_timing(trend)
    assert timing["state"] == "breakout_confirmed"
    assert timing["long_entry_eligible"] is False
    assert "breakout_volume_unconfirmed" in timing["flags"]


def test_missing_50dma_fails_closed():
    trend = _trend(100.0, 100.0, None, 100.0, slope50=None)
    timing = classify_timing(trend)
    assert timing["state"] == "insufficient_data"
    assert timing["long_entry_eligible"] is False


# ---------- 驗收 #1:三狀態分離 ----------

def test_states_are_independent_thesis_does_not_set_timing():
    # Strong thesis but damaged trend: timing stays damaged, exposure hedges,
    # thesis remains its own field.
    trend = _trend(80.0, 85.0, 95.0, 110.0, slope50=-0.02, rsi=25.0)
    result = evaluate_symbol(trend, thesis_state="strengthening")
    assert result["company_thesis_state"] == "strengthening"
    assert result["timing_state"] == "trend_damaged"
    assert result["exposure_posture"] == "hold_hedged"  # thesis intact → keep core, hedge
    assert result["add_allowed"] is False


def test_impaired_thesis_forces_re_underwrite_regardless_of_timing():
    trend = _trend(
        120.0, 110.0, 105.0, 95.0, slope50=0.03, slope20=0.03,
        rsi=62.0, donch20="breakout_up", volume_percentile=0.9,
    )
    result = evaluate_symbol(trend, thesis_state="impaired")
    assert result["exposure_posture"] == "re_underwrite"
    assert result["add_allowed"] is False


def test_leverage_in_downtrend_reduces_leverage():
    trend = _trend(80.0, 85.0, 95.0, 110.0, slope50=-0.02, rsi=25.0)
    exposure = derive_exposure_posture("intact", classify_timing(trend), has_leverage=True)
    assert exposure["posture"] == "reduce_leverage"


def test_healthy_trend_intact_thesis_allows_tactical_add():
    trend = _trend(
        102.0, 101.0, 98.0, 90.0, slope50=0.02, slope20=0.02, rsi=55.0
    )
    result = evaluate_symbol(trend, thesis_state="intact")
    assert result["exposure_posture"] == "tactical_add_ready"
    assert result["add_allowed"] is True


def test_state_vocabularies_are_stable():
    assert "insufficient_data" in TIMING_STATES
    assert "re_underwrite" in EXPOSURE_POSTURES
    assert "broken" in COMPANY_THESIS_STATES
