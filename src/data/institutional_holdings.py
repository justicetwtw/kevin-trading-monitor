"""13F 機構持股(EdgarTools)

掃描 src.config.institutions.INSTITUTIONS_TO_TRACK 的 12 家機構,
比對最近兩季 13F-HR,聚合對白名單股票的動向。

⚠ 共用 src.data.sec_edgar._ensure_edgar_identity() 守門。
"""

from collections import defaultdict
from datetime import datetime
from typing import Optional

from loguru import logger
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from src.config.institutions import INSTITUTIONS_TO_TRACK
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
def fetch_13f(institution_cik: str) -> dict:
    """抓單一機構最新 13F-HR + 上一季,計算持股變化"""
    _ensure_edgar_identity()
    try:
        company = Company(institution_cik)
        filings = company.get_filings(form="13F-HR").head(2)
        if not filings:
            return {}

        latest = filings[0]
        previous = filings[1] if len(filings) > 1 else None

        latest_holdings = _extract_holdings(latest)
        previous_holdings = _extract_holdings(previous) if previous else {}
        changes = _calc_changes(latest_holdings, previous_holdings)

        return {
            "cik": institution_cik,
            "filing_date": str(getattr(latest, "filing_date", "")),
            "holdings": latest_holdings,
            "changes": changes,
        }
    except (ValueError, RuntimeError):
        raise
    except Exception as e:
        logger.error(f"fetch_13f({institution_cik}) failed: {e}")
        return {}


def _extract_holdings(filing) -> dict:
    """從 13F filing 提取持股 dict {symbol: {shares, value}}"""
    if not filing:
        return {}
    try:
        obj = filing.obj()
        if not hasattr(obj, "infotable"):
            return {}
        holdings: dict = {}
        for row in obj.infotable:
            sym = getattr(row, "issuer", "") or getattr(row, "symbol", "")
            shares = float(getattr(row, "shares", 0) or 0)
            value = float(getattr(row, "value", 0) or 0)
            if sym:
                if sym not in holdings:
                    holdings[sym] = {"shares": 0.0, "value": 0.0}
                holdings[sym]["shares"] += shares
                holdings[sym]["value"] += value
        return holdings
    except Exception as e:
        logger.debug(f"_extract_holdings failed: {e}")
        return {}


def _calc_changes(latest: dict, previous: dict) -> dict:
    """比較兩季變化 → NEW / EXITED / INCREASED(>+10%)/ DECREASED(<-10%)/ HELD"""
    changes = {}
    all_syms = set(latest.keys()) | set(previous.keys())
    for sym in all_syms:
        l = latest.get(sym, {"shares": 0.0})["shares"]
        p = previous.get(sym, {"shares": 0.0})["shares"]
        if p == 0 and l > 0:
            changes[sym] = "NEW"
        elif l == 0 and p > 0:
            changes[sym] = "EXITED"
        elif l > p * 1.1:
            changes[sym] = "INCREASED"
        elif l < p * 0.9:
            changes[sym] = "DECREASED"
        else:
            changes[sym] = "HELD"
    return changes


def scan_all_institutions(target_symbols: Optional[list] = None) -> dict:
    """掃描全部 12 家機構,聚合對白名單股票的動向。
    target_symbols=None 時不過濾,回所有 symbol;傳入 list 則只回該子集。
    """
    aggregate = defaultdict(lambda: {
        "NEW": [], "INCREASED": [], "DECREASED": [], "EXITED": [], "HELD": []
    })

    for inst in INSTITUTIONS_TO_TRACK:
        try:
            data = fetch_13f(inst["cik"])
        except (ValueError, RuntimeError):
            raise
        except Exception as e:
            logger.warning(f"scan_all_institutions skipping {inst['name']}: {e}")
            continue
        if not data:
            continue
        for sym, change in data.get("changes", {}).items():
            if target_symbols and sym not in target_symbols:
                continue
            aggregate[sym][change].append(inst["name"])

    return {
        "scanned_at": datetime.now(TIMEZONE_US_MARKET).isoformat(),
        "n_institutions_scanned": len(INSTITUTIONS_TO_TRACK),
        "by_symbol": dict(aggregate),
    }
