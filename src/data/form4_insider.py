"""Form 4 內部人交易 - 雙模式(白名單監測 + cluster 偵測)

⚠ 共用 src.data.sec_edgar._ensure_edgar_identity() 守門:
SEC_EDGAR_USER_AGENT 未設一律 raise。

Cluster Buying 定義:30 天內 ≥3 位 unique insider 用 P 代碼買入 + 總額 ≥ $500k → tier 3 訊號
"""

from datetime import datetime, timedelta
from typing import Optional

from loguru import logger
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from src.config.settings import TIMEZONE_US_MARKET
from src.data.sec_edgar import EDGAR_AVAILABLE, _ensure_edgar_identity

if EDGAR_AVAILABLE:
    from edgar import Company  # type: ignore
else:
    Company = None  # type: ignore


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_not_exception_type((ValueError, RuntimeError)),
)
def fetch_form4(symbol: str, lookback_days: int = 30) -> list:
    """抓某檔股票過去 N 天的 Form 4"""
    _ensure_edgar_identity()
    try:
        company = Company(symbol)
        filings = company.get_filings(form="4").head(50)
        cutoff = datetime.now(TIMEZONE_US_MARKET).replace(tzinfo=None) - timedelta(days=lookback_days)

        results = []
        for f in filings:
            try:
                fd = f.filing_date
                if isinstance(fd, str):
                    fd = datetime.strptime(fd, "%Y-%m-%d")
                if not isinstance(fd, datetime) or fd < cutoff:
                    continue

                obj = f.obj()
                if not hasattr(obj, "transactions") or not obj.transactions:
                    continue

                for tx in obj.transactions:
                    shares = float(getattr(tx, "shares", 0) or 0)
                    price = float(getattr(tx, "price", 0) or 0)
                    code = getattr(tx, "code", "")
                    results.append({
                        "symbol": symbol,
                        "filing_date": fd.isoformat(),
                        "insider_name": getattr(obj, "owner_name", "Unknown"),
                        "insider_title": getattr(obj, "owner_title", ""),
                        "transaction_code": code,
                        "shares": shares,
                        "price": price,
                        "value_usd": shares * price,
                        "transaction_type": (
                            "BUY" if code == "P" else
                            "SELL" if code == "S" else
                            "OTHER"
                        ),
                    })
            except Exception as inner_e:
                logger.debug(f"Skipping Form 4 row for {symbol}: {inner_e}")
                continue
        return results
    except (ValueError, RuntimeError):
        raise
    except Exception as e:
        logger.error(f"fetch_form4({symbol}) failed: {e}")
        return []


def detect_cluster_buying(
    symbol: str,
    lookback_days: int = 30,
    min_insiders: int = 3,
    min_total_usd: float = 500_000,
) -> dict:
    """偵測 Cluster Buying:30 天內 ≥3 位 unique insider 用 P 代碼買入 + 總額 ≥ $500k → tier 3"""
    txs = fetch_form4(symbol, lookback_days)
    buys = [t for t in txs if t["transaction_code"] == "P"]
    unique_insiders = {t["insider_name"] for t in buys}
    total_value = sum(t["value_usd"] for t in buys)

    is_cluster = (
        len(unique_insiders) >= min_insiders
        and total_value >= min_total_usd
    )
    return {
        "symbol": symbol,
        "is_cluster": is_cluster,
        "tier": 3 if is_cluster else None,
        "n_insiders": len(unique_insiders),
        "total_value_usd": total_value,
        "transactions": buys,
        "lookback_days": lookback_days,
    }


def detect_ceo_cfo_buy(symbol: str, lookback_days: int = 7,
                       min_usd: float = 250_000) -> list:
    """偵測 CEO / CFO / President / Chairman 大額買入(P 代碼,≥ $250k)"""
    txs = fetch_form4(symbol, lookback_days)
    hits = []
    top_titles = ("CEO", "CFO", "PRESIDENT", "CHAIRMAN",
                  "CHIEF EXECUTIVE", "CHIEF FINANCIAL")
    for t in txs:
        title = (t["insider_title"] or "").upper()
        is_top = any(role in title for role in top_titles)
        if (
            t["transaction_code"] == "P"
            and is_top
            and t["value_usd"] >= min_usd
        ):
            hits.append(t)
    return hits


def scan_watchlist_form4(symbols: list, lookback_days: int = 30) -> dict:
    """整批掃白名單"""
    results = {}
    for s in symbols:
        try:
            results[s] = {
                "cluster": detect_cluster_buying(s, lookback_days),
                "ceo_cfo_buys": detect_ceo_cfo_buy(s, lookback_days=7),
            }
        except (ValueError, RuntimeError):
            raise  # identity / 安裝問題不該被吞
        except Exception as e:
            logger.warning(f"scan_watchlist_form4 skipping {s}: {e}")
            results[s] = {"cluster": {}, "ceo_cfo_buys": []}
    return results
