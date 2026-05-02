"""TSMC 月營收更新 (每月 10 號台北時間 16:00 cron)。

⚠ Section 12.9 spec 用 result.get("is_new") 判斷 → 模組不回 is_new。
真實邏輯:讀 history 前後 keys diff,出現新 year_month 才推。
"""

from loguru import logger

from src.alerts.alert_formatter import format_news_alert
from src.alerts.alert_router import route_alert
from src.data.tsmc_revenue import REVENUE_HISTORY_FILE, update_revenue_history
from src.storage.state_manager import read_json


def main() -> None:
    logger.info("=== run_tsmc_revenue start ===")
    try:
        before = read_json(REVENUE_HISTORY_FILE, default={})
        before_keys = set(before.keys()) if isinstance(before, dict) else set()

        history = update_revenue_history()
        after_keys = set(history.keys()) if isinstance(history, dict) else set()

        new_keys = after_keys - before_keys
        if not new_keys:
            logger.info("=== run_tsmc_revenue done (no new month) ===")
            return

        for k in sorted(new_keys):
            entry = history.get(k, {})
            yoy = entry.get("yoy_pct")
            if yoy is None:
                logger.warning(f"TSMC {k} has no yoy_pct; skip push")
                continue
            yoy_pct_display = yoy * 100  # 模組存 0.45 = 45%
            tier = 1 if abs(yoy_pct_display) >= 20 else (2 if abs(yoy_pct_display) >= 10 else 3)
            if tier == 3:
                continue
            alert = {
                "source": "TSMC 月營收",
                "tier": tier,
                "title": f"TSMC {k} 營收 YoY {yoy_pct_display:+.1f}%",
                "alert_level": "green" if tier == 1 else "yellow",
                "kind": "news",
            }
            alert["message"] = format_news_alert(alert)
            route_alert(alert)
        logger.info(f"=== run_tsmc_revenue done ({len(new_keys)} new month(s)) ===")
    except Exception as e:
        logger.error(f"run_tsmc_revenue crashed: {e}")


if __name__ == "__main__":
    main()
