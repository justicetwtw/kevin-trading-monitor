"""成交量指標 - 均量、量比、量爆、量價背離

對外入口包 try/except,失敗回 None / {"divergence": False}。
"""

import pandas as pd
from loguru import logger


def get_volume_avg(df: pd.DataFrame, length: int = 20) -> float | None:
    try:
        if df is None or df.empty or "Volume" not in df.columns:
            return None
        rolled = df["Volume"].rolling(length).mean()
        if rolled.dropna().empty:
            return None
        return float(rolled.iloc[-1])
    except Exception as e:
        logger.warning(f"get_volume_avg failed: {e}")
        return None


def get_volume_ratio(df: pd.DataFrame, length: int = 20) -> float | None:
    """當日成交量 / 均量。失敗或無資料回 None。"""
    try:
        avg = get_volume_avg(df, length)
        if not avg:
            return None
        return float(df["Volume"].iloc[-1] / avg)
    except Exception as e:
        logger.warning(f"get_volume_ratio failed: {e}")
        return None


def detect_volume_surge(df: pd.DataFrame, multiplier: float = 1.5) -> bool:
    """量爆(>= 均量 N 倍)。失敗回 False。"""
    try:
        ratio = get_volume_ratio(df)
        return ratio is not None and ratio >= multiplier
    except Exception as e:
        logger.warning(f"detect_volume_surge failed: {e}")
        return False


def detect_volume_price_divergence(df: pd.DataFrame, lookback: int = 5) -> dict:
    """量價背離 - 價漲量縮(bearish)/ 價跌量縮(bullish, 賣壓減弱)。失敗回 {"divergence": False}。"""
    try:
        if df is None or df.empty or len(df) < lookback * 2:
            return {"divergence": False}
        recent = df.iloc[-lookback:]
        prior = df.iloc[-lookback * 2:-lookback]
        if prior.empty or recent.empty:
            return {"divergence": False}

        price_change = (recent["Close"].iloc[-1] - recent["Close"].iloc[0]) / recent["Close"].iloc[0]
        prior_vol_mean = prior["Volume"].mean()
        if not prior_vol_mean:
            return {"divergence": False}
        vol_change = (recent["Volume"].mean() - prior_vol_mean) / prior_vol_mean

        bearish_div = price_change > 0.02 and vol_change < -0.2
        bullish_div = price_change < -0.02 and vol_change < -0.2

        return {
            "divergence": bool(bearish_div or bullish_div),
            "type": "bearish" if bearish_div else ("bullish" if bullish_div else None),
            "price_change_pct": float(price_change),
            "volume_change_pct": float(vol_change),
        }
    except Exception as e:
        logger.warning(f"detect_volume_price_divergence failed: {e}")
        return {"divergence": False}
