"""Black-Scholes Greeks 計算(IV 由 yfinance 取得)"""

import math
from scipy.stats import norm


def calc_d1_d2(S: float, K: float, T: float, r: float, sigma: float) -> tuple:
    """Black-Scholes d1 / d2"""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0, 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return d1, d2


def calc_delta(
    S: float, K: float, T: float, r: float, sigma: float,
    option_type: str = "call",
) -> float:
    """Delta"""
    d1, _ = calc_d1_d2(S, K, T, r, sigma)
    if option_type == "call":
        return float(norm.cdf(d1))
    return float(norm.cdf(d1) - 1)


def calc_bs_price(
    S: float, K: float, T: float, r: float, sigma: float,
    option_type: str = "call",
) -> float:
    """Black-Scholes 理論價(per share)。T<=0 / sigma<=0 / S<=0 / K<=0 回 0.0。"""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    d1, d2 = calc_d1_d2(S, K, T, r, sigma)
    if option_type == "call":
        return float(S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2))
    return float(K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1))


def calc_gamma(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0 or S <= 0:
        return 0.0
    d1, _ = calc_d1_d2(S, K, T, r, sigma)
    return float(norm.pdf(d1) / (S * sigma * math.sqrt(T)))


def calc_theta(
    S: float, K: float, T: float, r: float, sigma: float,
    option_type: str = "call",
) -> float:
    """每日 Theta(年化 / 365)"""
    if T <= 0 or sigma <= 0:
        return 0.0
    d1, d2 = calc_d1_d2(S, K, T, r, sigma)
    term1 = -(S * norm.pdf(d1) * sigma) / (2 * math.sqrt(T))
    if option_type == "call":
        term2 = -r * K * math.exp(-r * T) * norm.cdf(d2)
    else:
        term2 = r * K * math.exp(-r * T) * norm.cdf(-d2)
    return (term1 + term2) / 365


def calc_vega(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0:
        return 0.0
    d1, _ = calc_d1_d2(S, K, T, r, sigma)
    return float(S * norm.pdf(d1) * math.sqrt(T) / 100)  # per 1% IV change


def calc_all_greeks(
    S: float, K: float, T: float, r: float, sigma: float,
    option_type: str = "call",
) -> dict:
    return {
        "delta": calc_delta(S, K, T, r, sigma, option_type),
        "gamma": calc_gamma(S, K, T, r, sigma),
        "theta": calc_theta(S, K, T, r, sigma, option_type),
        "vega": calc_vega(S, K, T, r, sigma),
    }
