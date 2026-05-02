"""Batch 8 Step 1 — calc_bs_price unit tests。

驗證 Black-Scholes 理論價:
- ATM call/put put-call parity
- 邊界值(T<=0, sigma<=0, S/K<=0)回 0.0
- 深 ITM call ≈ S - K * e^(-rT)
- 已知值對照(教科書數字)
"""

import math

from src.data.greeks_calculator import calc_bs_price


def test_atm_call_positive():
    """ATM call(S=K=100, T=1, sigma=0.2, r=0.05)有確定的教科書值 ≈ 10.4506"""
    p = calc_bs_price(S=100, K=100, T=1.0, r=0.05, sigma=0.20, option_type="call")
    assert abs(p - 10.4506) < 0.01, f"expected ~10.4506, got {p}"


def test_atm_put_parity():
    """Put-call parity: C - P = S - K * e^(-rT)"""
    S, K, T, r, sigma = 100, 100, 1.0, 0.05, 0.20
    c = calc_bs_price(S, K, T, r, sigma, "call")
    p = calc_bs_price(S, K, T, r, sigma, "put")
    parity_diff = c - p
    expected = S - K * math.exp(-r * T)
    assert abs(parity_diff - expected) < 0.01, f"parity broken: {parity_diff} vs {expected}"


def test_boundary_zero_T_returns_zero():
    """T <= 0 → 0.0(不應拋例外)"""
    assert calc_bs_price(100, 100, 0, 0.05, 0.2, "call") == 0.0
    assert calc_bs_price(100, 100, -1, 0.05, 0.2, "put") == 0.0


def test_boundary_zero_sigma_returns_zero():
    """sigma <= 0 → 0.0"""
    assert calc_bs_price(100, 100, 1.0, 0.05, 0, "call") == 0.0
    assert calc_bs_price(100, 100, 1.0, 0.05, -0.1, "put") == 0.0


def test_deep_itm_call_approaches_intrinsic():
    """深 ITM call(S=200, K=100)≈ S - K*e^(-rT),時間價值極小"""
    S, K, T, r, sigma = 200, 100, 1.0, 0.05, 0.20
    p = calc_bs_price(S, K, T, r, sigma, "call")
    intrinsic = S - K * math.exp(-r * T)
    assert p >= intrinsic - 0.01, f"deep ITM call {p} below discounted intrinsic {intrinsic}"
    assert p < intrinsic + 1.0, f"deep ITM call {p} too far above intrinsic {intrinsic}"


def test_deep_otm_put_small_positive():
    """深 OTM put(S=200, K=100)價值極小但非負"""
    p = calc_bs_price(S=200, K=100, T=1.0, r=0.05, sigma=0.20, option_type="put")
    assert 0 <= p < 1.0, f"deep OTM put should be ~0, got {p}"
