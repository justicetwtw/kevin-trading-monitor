"""形態識別 - 阻力/支撐區、阻力區拒絕(上影線)。

對外入口包 try/except,失敗回 {} / False。
"""

import pandas as pd
from loguru import logger


def find_support_resistance(df: pd.DataFrame, lookback: int = 60,
                             tolerance: float = 0.02) -> dict:
    """簡化版支撐/阻力 - 用近 lookback 日的高低點。失敗回 {}。"""
    try:
        if df is None or df.empty or len(df) < lookback:
            return {}
        recent = df.iloc[-lookback:]
        highs = recent["High"].values
        lows = recent["Low"].values
        close = float(df["Close"].iloc[-1])

        resistance_levels = sorted(set(round(float(h), 2) for h in highs if h > close * 1.005))
        support_levels = sorted(
            set(round(float(l), 2) for l in lows if l < close * 0.995),
            reverse=True,
        )

        nearest_resistance = resistance_levels[0] if resistance_levels else None
        nearest_support = support_levels[0] if support_levels else None

        return {
            "current": close,
            "nearest_resistance": nearest_resistance,
            "nearest_support": nearest_support,
            "near_resistance": (
                bool((nearest_resistance - close) / close < tolerance)
                if nearest_resistance is not None else False
            ),
            "near_support": (
                bool((close - nearest_support) / close < tolerance)
                if nearest_support is not None else False
            ),
        }
    except Exception as e:
        logger.warning(f"find_support_resistance failed: {e}")
        return {}


def detect_resistance_rejection(df: pd.DataFrame, lookback: int = 5) -> bool:
    """阻力區拒絕 - 近 N 日有 wick 上影線(>= body 2x)。失敗回 False。"""
    try:
        if df is None or df.empty or len(df) < lookback:
            return False
        recent = df.iloc[-lookback:]
        for _, row in recent.iterrows():
            upper_wick = row["High"] - max(row["Open"], row["Close"])
            body = abs(row["Close"] - row["Open"])
            if body > 0 and upper_wick > body * 2:
                return True
        return False
    except Exception as e:
        logger.warning(f"detect_resistance_rejection failed: {e}")
        return False
