"""SEC EDGAR 8-K filings 抓取(EdgarTools)

⚠ SEC 規定所有 EDGAR 請求必須帶 User-Agent 識別身份。
SEC_EDGAR_USER_AGENT 從 src.config.settings 讀,未設一律 raise(避免無 identity 觸發 IP ban)。
"""

from datetime import datetime, timedelta
from typing import Optional

from loguru import logger
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from src.config.settings import SEC_EDGAR_USER_AGENT, TIMEZONE_US_MARKET

# edgartools import 失敗不應阻擋整個 module 載入(避免在沒裝套件的環境炸掉 import smoke test)
try:
    from edgar import Company, set_identity
    EDGAR_AVAILABLE = True
except ImportError as _e:
    EDGAR_AVAILABLE = False
    Company = None  # type: ignore
    set_identity = None  # type: ignore
    logger.warning(f"edgartools not installed: {_e}")


_IDENTITY_SET = False


def _ensure_edgar_identity() -> None:
    """每個 fetch 函式入口呼叫一次。
    - SEC_EDGAR_USER_AGENT 未設 → raise ValueError(不允許靜默 fallback)
    - edgartools 未裝 → raise RuntimeError(安裝環境不對)
    - 已設過 identity → 跳過(set_identity 不可重複呼叫過密集)
    """
    global _IDENTITY_SET
    if not EDGAR_AVAILABLE:
        raise RuntimeError(
            "edgartools not installed; cannot query SEC EDGAR"
        )
    if not SEC_EDGAR_USER_AGENT:
        raise ValueError(
            "SEC_EDGAR_USER_AGENT not set. SEC requires identification on all EDGAR "
            "requests; refusing to fire request without identity to avoid IP ban."
        )
    if not _IDENTITY_SET:
        set_identity(SEC_EDGAR_USER_AGENT)
        _IDENTITY_SET = True


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    # ValueError(missing UA)/ RuntimeError(edgartools 未裝)立即傳播,不重試
    retry=retry_if_not_exception_type((ValueError, RuntimeError)),
)
def fetch_recent_8k(symbol: str, lookback_hours: int = 2) -> list:
    """抓某檔股票最近的 8-K filings"""
    _ensure_edgar_identity()
    try:
        company = Company(symbol)
        filings = company.get_filings(form="8-K").head(10)
        cutoff = datetime.now(TIMEZONE_US_MARKET).replace(tzinfo=None) - timedelta(hours=lookback_hours)

        results = []
        for f in filings:
            filing_date = f.filing_date
            if isinstance(filing_date, str):
                try:
                    filing_date = datetime.strptime(filing_date, "%Y-%m-%d")
                except ValueError:
                    continue
            if not isinstance(filing_date, datetime):
                continue
            if filing_date < cutoff:
                continue
            results.append({
                "symbol": symbol,
                "form": "8-K",
                "filing_date": filing_date.isoformat(),
                "accession_no": str(getattr(f, "accession_no", "")),
                "url": getattr(f, "homepage_url", ""),
                "items": _extract_8k_items(f),
            })
        return results
    except (ValueError, RuntimeError):
        # USER_AGENT 缺漏 / edgartools 缺裝 → 直接傳播
        raise
    except Exception as e:
        logger.error(f"fetch_recent_8k({symbol}) failed: {e}")
        return []


def _extract_8k_items(filing) -> list:
    """提取 8-K 涉及的 Item 編號(1.01 / 2.02 / 5.02 等)"""
    try:
        items = filing.items if hasattr(filing, "items") else []
        return [str(i) for i in items]
    except Exception:
        return []


def scan_watchlist_8k(symbols: list, lookback_hours: int = 2) -> list:
    """掃描白名單所有股票的 8-K"""
    all_filings = []
    for s in symbols:
        try:
            all_filings.extend(fetch_recent_8k(s, lookback_hours))
        except (ValueError, RuntimeError):
            raise  # identity / 安裝問題不該被吞
        except Exception as e:
            logger.warning(f"scan_watchlist_8k skipping {s}: {e}")
    return all_filings


# 8-K Item 重要性分類
ITEM_PRIORITY = {
    "1.01": "high",   # Material Definitive Agreement
    "1.02": "high",   # Termination of Material Agreement
    "2.01": "high",   # Acquisition/Disposition
    "2.02": "high",   # Earnings Release
    "2.05": "medium", # Costs from Exit
    "5.02": "medium", # Departure of Director/Officer
    "7.01": "medium", # Reg FD Disclosure
    "8.01": "low",    # Other Events
}


def classify_8k_priority(items: list) -> str:
    """回傳該 8-K 最高優先級"""
    priorities = [ITEM_PRIORITY.get(i, "low") for i in items]
    if "high" in priorities:
        return "high"
    if "medium" in priorities:
        return "medium"
    return "low"
