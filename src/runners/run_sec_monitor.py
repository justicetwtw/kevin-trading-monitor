"""SEC EDGAR 8-K 監控 (1 小時 cron)。

⚠ Section 12.3 spec 已廢棄(fetch_recent_filings(forms=[8-K,10-Q,10-K]) 不存在)。
真實實作:scan_watchlist_8k(ALL_US_STOCKS, 2h) → 自管 sec_seen.json 去重 → cold_start 24h → push。
偏離決策:**只跑 8-K**(模組未實作 10-Q/10-K)。10-Q/10-K + insider 大額賣出 alert 留 Phase 3。

US_UNIVERSE 不存在 → 用 ALL_US_STOCKS(不含 ETF,SEC 不報 ETF)。
"""

from datetime import datetime, timezone

from dateutil.parser import isoparse
from loguru import logger

from src.alerts.alert_formatter import format_news_alert
from src.alerts.alert_router import route_alert
from src.config.universe import ALL_US_STOCKS
from src.data.sec_edgar import classify_8k_priority, scan_watchlist_8k
from src.runners._cold_start import filter_with_cold_start_protection
from src.storage.state_manager import read_json, write_json

SEC_SEEN_FILE = "sec_seen.json"
MAX_SEEN = 5000


def _get_filing_ts(f: dict):
    s = f.get("filing_date")
    if not s:
        return None
    try:
        return isoparse(s)
    except (ValueError, TypeError):
        return None


def _priority_to_alert(priority: str) -> tuple[int, str]:
    if priority == "high":
        return 1, "green"
    return 2, "yellow"


def main() -> None:
    logger.info("=== run_sec_monitor start ===")
    try:
        seen_before = read_json(SEC_SEEN_FILE, default={})
        if not isinstance(seen_before, dict):
            seen_before = {}

        filings = scan_watchlist_8k(ALL_US_STOCKS, lookback_hours=2) or []
        if not filings:
            logger.info("=== run_sec_monitor done (0 filings) ===")
            return

        # Dedup by accession_no
        deduped = [
            f for f in filings
            if f.get("accession_no") and f["accession_no"] not in seen_before
        ]

        to_process, to_mark = filter_with_cold_start_protection(
            items=deduped,
            seen_set=seen_before,
            get_created_at=_get_filing_ts,
            cold_start_window_hours=24,
        )

        # Mark all (process + mark) into seen
        now_iso = datetime.now(timezone.utc).isoformat()
        for f in to_process + to_mark:
            seen_before[f["accession_no"]] = {
                "seen_at": now_iso,
                "symbol": f.get("symbol"),
                "filing_date": f.get("filing_date", ""),
            }
        if len(seen_before) > MAX_SEEN:
            sorted_items = sorted(
                seen_before.items(), key=lambda x: x[1].get("seen_at", "")
            )
            seen_before = dict(sorted_items[-MAX_SEEN:])
        write_json(SEC_SEEN_FILE, seen_before)

        pushed = 0
        for f in to_process:
            try:
                priority = classify_8k_priority(f.get("items", []))
                if priority == "low":
                    continue
                tier, level = _priority_to_alert(priority)
                alert = {
                    "source": f"SEC/{f.get('symbol', '?')}",
                    "form_type": "8-K",
                    "title": f"8-K Items {','.join(f.get('items', []))} — {f.get('symbol', '?')}",
                    "url": f.get("url", ""),
                    "tier": tier,
                    "alert_level": level,
                    "kind": "news",
                    "scan_time": now_iso,
                }
                alert["message"] = format_news_alert(alert)
                if route_alert(alert):
                    pushed += 1
            except Exception as e:
                logger.error(f"SEC per-filing failed (skip): {e}")

        logger.info(f"=== run_sec_monitor done ({pushed} pushed) ===")
    except Exception as e:
        logger.error(f"run_sec_monitor crashed: {e}")


if __name__ == "__main__":
    main()
