"""yfinance 價格資料 + 選擇權鏈包裝"""

import time
from datetime import datetime
from typing import Optional

import pandas as pd
import yfinance as yf
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config.settings import TIMEZONE_US_MARKET
from src.storage.state_manager import DATA_STORE_DIR

PRICE_CACHE_PATH = DATA_STORE_DIR / "price_history.parquet"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_history(
    symbol: str,
    period: str = "1y",
    interval: str = "1d",
) -> pd.DataFrame:
    """抓取單一標的歷史價格"""
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval, auto_adjust=False)
        if df.empty:
            logger.warning(f"Empty history for {symbol}")
            return pd.DataFrame()
        if df.index.tz is not None:
            df.index = df.index.tz_convert(TIMEZONE_US_MARKET)
        df["Symbol"] = symbol
        return df
    except Exception as e:
        logger.error(f"fetch_history({symbol}) failed: {e}")
        raise


def fetch_history_batch(
    symbols: list,
    period: str = "1y",
    interval: str = "1d",
    sleep_sec: float = 0.5,
) -> dict:
    """批次抓取多檔(序列化以免被 rate limit)"""
    out = {}
    for s in symbols:
        try:
            out[s] = fetch_history(s, period=period, interval=interval)
        except Exception as e:
            logger.error(f"Skipping {s}: {e}")
            out[s] = pd.DataFrame()
        time.sleep(sleep_sec)
    return out


def get_latest_price(symbol: str) -> Optional[float]:
    """即時報價(15-20 分延遲)"""
    try:
        df = fetch_history(symbol, period="2d", interval="1m")
        if df.empty:
            return None
        return float(df["Close"].iloc[-1])
    except Exception as e:
        logger.error(f"get_latest_price({symbol}) failed: {e}")
        return None


def get_52w_high_low(symbol: str) -> dict:
    """52 週高低點"""
    df = fetch_history(symbol, period="1y")
    if df.empty:
        return {"high": None, "low": None, "current": None,
                "pct_from_high": None, "pct_from_low": None}
    high = float(df["High"].max())
    low = float(df["Low"].min())
    current = float(df["Close"].iloc[-1])
    return {
        "high": high,
        "low": low,
        "current": current,
        "pct_from_high": (current - high) / high,
        "pct_from_low": (current - low) / low,
    }


def fetch_option_chain(symbol: str, expiry: Optional[str] = None) -> dict:
    """抓取選擇權鏈
    回傳: {"calls": DataFrame, "puts": DataFrame, "expiry": str, "underlying": float}
    """
    try:
        ticker = yf.Ticker(symbol)
        expiries = ticker.options
        if not expiries:
            logger.warning(f"No options for {symbol}")
            return {}

        chosen = expiry if expiry in expiries else expiries[0]
        chain = ticker.option_chain(chosen)
        underlying = get_latest_price(symbol)
        return {
            "calls": chain.calls,
            "puts": chain.puts,
            "expiry": chosen,
            "underlying": underlying,
            "all_expiries": list(expiries),
        }
    except Exception as e:
        logger.error(f"fetch_option_chain({symbol}) failed: {e}")
        return {}


def find_option_by_dte_delta(
    symbol: str,
    target_dte_min: int,
    target_dte_max: int,
    target_delta: float,
    option_type: str = "call",
) -> Optional[dict]:
    """根據 DTE + Delta 範圍找最接近的選擇權合約"""
    from src.data.greeks_calculator import calc_delta

    ticker = yf.Ticker(symbol)
    expiries = ticker.options
    if not expiries:
        return None

    underlying = get_latest_price(symbol)
    if underlying is None:
        return None

    today = datetime.now(TIMEZONE_US_MARKET).date()
    candidates = []

    for exp_str in expiries:
        exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
        dte = (exp_date - today).days
        if not (target_dte_min <= dte <= target_dte_max):
            continue

        try:
            chain = ticker.option_chain(exp_str)
        except Exception as e:
            logger.warning(f"option_chain({symbol}, {exp_str}) failed: {e}")
            continue
        df = chain.calls if option_type == "call" else chain.puts

        for _, row in df.iterrows():
            iv = row.get("impliedVolatility", 0.3)
            strike = float(row["strike"])
            try:
                delta = calc_delta(
                    S=underlying, K=strike, T=dte / 365, r=0.045,
                    sigma=iv, option_type=option_type,
                )
            except Exception:
                continue
            candidates.append({
                "expiry": exp_str,
                "dte": dte,
                "strike": strike,
                "bid": float(row.get("bid", 0)),
                "ask": float(row.get("ask", 0)),
                "iv": iv,
                "delta": delta,
                "delta_diff": abs(abs(delta) - abs(target_delta)),
            })

    if not candidates:
        return None
    return min(candidates, key=lambda x: x["delta_diff"])


def cache_price_history(symbols: list, period: str = "1y") -> None:
    """更新價格快取(parquet)"""
    data = fetch_history_batch(symbols, period=period)
    rows = []
    for sym, df in data.items():
        if df.empty:
            continue
        df = df.copy()
        df["Symbol"] = sym
        rows.append(df.reset_index())
    if rows:
        combined = pd.concat(rows, ignore_index=True)
        combined.to_parquet(PRICE_CACHE_PATH, compression="snappy")
        logger.info(f"Cached {len(rows)} symbols → {PRICE_CACHE_PATH}")


def load_cached_history(symbol: str) -> pd.DataFrame:
    """從 cache 載入單檔(階段 3 回測用)"""
    if not PRICE_CACHE_PATH.exists():
        return pd.DataFrame()
    df = pd.read_parquet(PRICE_CACHE_PATH)
    return df[df["Symbol"] == symbol].copy()
