"""基礎技術指標 - RSI / Bollinger Bands / MA / ADX

注意:使用 pandas_ta_classic(不是 pandas_ta)。
對外入口包 try/except,失敗回 None / {};不偽造中性值。
"""

import pandas as pd
import pandas_ta_classic as ta  # noqa: F401  (registers df.ta accessor)
from loguru import logger


def add_rsi(df: pd.DataFrame, length: int = 14) -> pd.DataFrame:
    df = df.copy()
    df.ta.rsi(length=length, append=True)
    return df


def get_rsi_latest(df: pd.DataFrame, length: int = 14) -> float | None:
    try:
        df = add_rsi(df, length)
        col = f"RSI_{length}"
        if col not in df.columns or df[col].isna().all():
            return None
        return float(df[col].dropna().iloc[-1])
    except Exception as e:
        logger.warning(f"get_rsi_latest failed: {e}")
        return None


def add_bbands(df: pd.DataFrame, length: int = 20, std: float = 2.0) -> pd.DataFrame:
    df = df.copy()
    df.ta.bbands(length=length, std=std, append=True)
    return df


def get_bbands_position(df: pd.DataFrame, length: int = 20, std: float = 2.0) -> dict:
    """回傳 BB 位置: pct(0=下軌,1=上軌)、是否觸碰上下軌。失敗回 {}。"""
    try:
        df = add_bbands(df, length, std)
        upper_col = f"BBU_{length}_{std}"
        lower_col = f"BBL_{length}_{std}"
        if upper_col not in df.columns or lower_col not in df.columns:
            return {}
        upper_series = df[upper_col].dropna()
        lower_series = df[lower_col].dropna()
        if upper_series.empty or lower_series.empty:
            return {}
        upper = upper_series.iloc[-1]
        lower = lower_series.iloc[-1]
        close = df["Close"].iloc[-1]
        width = upper - lower
        pct = (close - lower) / width if width else 0.5
        return {
            "upper": float(upper),
            "lower": float(lower),
            "close": float(close),
            "pct": float(pct),
            "touch_upper": bool(close >= upper * 0.995),
            "touch_lower": bool(close <= lower * 1.005),
        }
    except Exception as e:
        logger.warning(f"get_bbands_position failed: {e}")
        return {}


def add_ma(df: pd.DataFrame, lengths: list | None = None) -> pd.DataFrame:
    df = df.copy()
    lengths = lengths or [20, 50, 100, 200]
    for n in lengths:
        df[f"SMA_{n}"] = df["Close"].rolling(n).mean()
    return df


def get_ma_position(df: pd.DataFrame) -> dict:
    """價格相對 MA 的位置。失敗回 {}。"""
    try:
        df = add_ma(df)
        close = df["Close"].iloc[-1]
        out: dict = {"close": float(close)}
        for n in [20, 50, 100, 200]:
            col = f"SMA_{n}"
            if col in df.columns and not df[col].isna().all():
                ma_val = df[col].dropna().iloc[-1]
                out[f"sma_{n}"] = float(ma_val)
                out[f"pct_from_sma_{n}"] = float((close - ma_val) / ma_val)
                out[f"above_sma_{n}"] = bool(close > ma_val)
        return out
    except Exception as e:
        logger.warning(f"get_ma_position failed: {e}")
        return {}


def add_adx(df: pd.DataFrame, length: int = 14) -> pd.DataFrame:
    df = df.copy()
    df.ta.adx(length=length, append=True)
    return df


def get_adx_latest(df: pd.DataFrame, length: int = 14) -> float | None:
    try:
        df = add_adx(df, length)
        col = f"ADX_{length}"
        if col not in df.columns or df[col].isna().all():
            return None
        return float(df[col].dropna().iloc[-1])
    except Exception as e:
        logger.warning(f"get_adx_latest failed: {e}")
        return None


def get_consecutive_up_days(df: pd.DataFrame) -> int:
    """連續上漲天數。失敗或空資料回 0。"""
    try:
        if df is None or df.empty or "Close" not in df.columns:
            return 0
        closes = df["Close"].values
        count = 0
        for i in range(len(closes) - 1, 0, -1):
            if closes[i] > closes[i - 1]:
                count += 1
            else:
                break
        return int(count)
    except Exception as e:
        logger.warning(f"get_consecutive_up_days failed: {e}")
        return 0
