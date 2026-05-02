"""IBD Distribution Days 演算法

規則:過去 lookback 個交易日內,SPY(或 QQQ)收盤跌 >= min_drop_pct 且當日量 > 前一日量,記為派發日。
門檻:0-3 healthy / 4-5 pressure / 6+ distribution(見 src/config/thresholds.py)。

對外入口包 try/except,失敗回安全預設 dict。datetime 帶時區。
"""

from datetime import datetime, timezone

from loguru import logger

from src.config.thresholds import DISTRIBUTION_DAYS_RULE
from src.data.price_data import fetch_history
from src.storage.state_manager import write_json


def detect_distribution_days(symbol: str = "SPY", lookback: int = 25) -> dict:
    """偵測過去 lookback 個交易日內的派發日。失敗回 {count:0, days:[], level:"unknown"}。"""
    try:
        df = fetch_history(symbol, period="2mo", interval="1d")
        if df is None or df.empty or len(df) < lookback + 1:
            return {
                "symbol": symbol,
                "lookback": lookback,
                "count": 0,
                "days": [],
                "level": "unknown",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }

        df = df.iloc[-(lookback + 1):]
        distribution_days = []

        for i in range(1, len(df)):
            today = df.iloc[i]
            yesterday = df.iloc[i - 1]
            if not yesterday["Close"]:
                continue
            price_drop_pct = (today["Close"] - yesterday["Close"]) / yesterday["Close"]
            vol_increased = today["Volume"] > yesterday["Volume"]

            if price_drop_pct <= -DISTRIBUTION_DAYS_RULE["min_drop_pct"] and vol_increased:
                distribution_days.append({
                    "date": str(today.name.date()),
                    "drop_pct": float(price_drop_pct),
                    "volume": int(today["Volume"]),
                    "prev_volume": int(yesterday["Volume"]),
                })

        count = len(distribution_days)
        thresholds = DISTRIBUTION_DAYS_RULE["thresholds"]
        if count <= thresholds["healthy"]:
            level = "healthy"
        elif count <= thresholds["pressure"]:
            level = "pressure"
        else:
            level = "distribution"

        result = {
            "symbol": symbol,
            "lookback": lookback,
            "count": count,
            "days": distribution_days,
            "level": level,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            write_json("distribution_days_log.json", result)
        except Exception as write_err:
            logger.warning(f"distribution_days write_json failed (non-fatal): {write_err}")

        return result
    except Exception as e:
        logger.warning(f"detect_distribution_days({symbol}) failed: {e}")
        return {
            "symbol": symbol,
            "lookback": lookback,
            "count": 0,
            "days": [],
            "level": "unknown",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
        }
