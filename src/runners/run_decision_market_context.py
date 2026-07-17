"""Refresh public market context used by the decision-readiness engine.

The output is timing/risk context, not valuation. Missing symbols remain explicit
and make the workflow non-zero after the safe state is written.
"""

from __future__ import annotations

import math
import sys
from datetime import date, datetime, timezone
from typing import Any

from loguru import logger

from src.data.price_data import fetch_history
from src.storage.state_manager import read_json, write_json

OUTPUT_FILE = "decision_market_context.json"
# Calendar-day bound (covers long holiday weekends). A complete series whose
# last bar is older than this is stale price data, not a healthy snapshot.
MAX_MARKET_AGE_DAYS = 5


def _return(close, lookback: int) -> float | None:
    if len(close) <= lookback:
        return None
    start = float(close.iloc[-lookback - 1])
    end = float(close.iloc[-1])
    if start <= 0:
        return None
    return round((end / start) - 1, 6)


def _realized_vol(close, window: int = 20) -> float | None:
    returns = close.pct_change().dropna().tail(window)
    if len(returns) < window:
        return None
    value = float(returns.std(ddof=1)) * math.sqrt(252)
    return round(value, 6) if math.isfinite(value) else None


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def summarize_history(
    symbol: str, frame, *, today: date | None = None
) -> dict[str, Any]:
    if frame is None or frame.empty or "Close" not in frame or "High" not in frame:
        return {
            "symbol": symbol,
            "status": "unavailable",
            "source": "yfinance_delayed_public_market_data",
            "error_code": "empty_price_history",
        }
    ordered = frame.sort_index()
    close = ordered["Close"].dropna()
    high = ordered["High"].dropna()
    if close.empty or high.empty:
        return {
            "symbol": symbol,
            "status": "unavailable",
            "source": "yfinance_delayed_public_market_data",
            "error_code": "missing_close_or_high",
        }
    current = float(close.iloc[-1])
    high_52w = float(high.tail(252).max())
    as_of_index = close.index[-1]
    as_of = as_of_index.isoformat() if hasattr(as_of_index, "isoformat") else str(as_of_index)
    as_of_date = (
        as_of_index.date()
        if hasattr(as_of_index, "date")
        else _parse_date(as_of)
    )
    reference = today or datetime.now(timezone.utc).date()
    if as_of_date is not None and (reference - as_of_date).days > MAX_MARKET_AGE_DAYS:
        # Metric completeness alone must not label stale price data healthy:
        # downstream freshness gates compare against this same as-of.
        return {
            "symbol": symbol,
            "status": "unavailable",
            "current_price": round(current, 6),
            "as_of": as_of,
            "source": "yfinance_delayed_public_market_data",
            "sample_count": int(len(close)),
            "error_code": "stale_price_history",
            "max_age_days": MAX_MARKET_AGE_DAYS,
        }
    metrics = {
        "return_1m": _return(close, 21),
        "return_3m": _return(close, 63),
        "return_6m": _return(close, 126),
        "pct_from_52w_high": round((current / high_52w) - 1, 6) if high_52w > 0 else None,
        "realized_vol_20d": _realized_vol(close),
    }
    missing = sorted(key for key, value in metrics.items() if value is None)
    return {
        "symbol": symbol,
        "status": "healthy" if not missing else "partial",
        "current_price": round(current, 6),
        "as_of": as_of,
        "source": "yfinance_delayed_public_market_data",
        "sample_count": int(len(close)),
        **metrics,
        "missing_metrics": missing,
        "limitations": [
            "delayed/unofficial market data",
            "timing and risk context only; not valuation or a price target",
        ],
    }


def main() -> int:
    allocation = read_json("capital_allocation.json", default={})
    candidates = allocation.get("candidates") if isinstance(allocation, dict) else []
    symbols = sorted(
        {
            str(item.get("symbol"))
            for item in (candidates or [])
            if isinstance(item, dict) and item.get("symbol") and not item.get("_example")
        }
    )
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        try:
            rows.append(summarize_history(symbol, fetch_history(symbol, period="1y", interval="1d")))
        except Exception as exc:
            logger.error(f"decision market context failed for {symbol}: {type(exc).__name__}")
            rows.append(
                {
                    "symbol": symbol,
                    "status": "unavailable",
                    "source": "yfinance_delayed_public_market_data",
                    "error_code": type(exc).__name__,
                }
            )
    unavailable = [row["symbol"] for row in rows if row.get("status") == "unavailable"]
    partial = [row["symbol"] for row in rows if row.get("status") == "partial"]
    if not symbols:
        # An empty candidate list is a degraded input (corrupt or emptied
        # allocation doc), never a healthy run.
        status = "no_candidates"
    elif unavailable:
        status = "degraded"
    elif partial:
        status = "partial"
    else:
        status = "healthy"
    document = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "rows": rows,
        "unavailable_count": len(unavailable),
        "partial_count": len(partial),
        "safe_error_symbols": unavailable,
        "max_age_days": MAX_MARKET_AGE_DAYS,
        "contract": "market_context_only_not_valuation_or_trade_instruction",
    }
    if not write_json(OUTPUT_FILE, document):
        logger.error("failed to write decision market context state")
        return 1
    logger.info(
        f"decision market context: {len(rows)} symbols, "
        f"unavailable={len(unavailable)}, partial={len(partial)}, status={status}"
    )
    # AGENTS.md forbids disguising unavailable/empty/partial as success: the
    # safe state is committed above, then any non-healthy status fails the
    # workflow so degraded coverage is operationally visible, not just noted.
    return 0 if status == "healthy" else 1


if __name__ == "__main__":
    sys.exit(main())
