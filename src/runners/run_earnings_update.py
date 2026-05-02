"""每日財報行事曆更新 (cron)。

⚠ Section 12.8 spec 寫 refresh_earnings_calendar() 不存在 → 改用 update_calendar(symbols)。
"""

from loguru import logger

from src.config.universe import ALL_US_STOCKS
from src.data.earnings_calendar import update_calendar


def main() -> None:
    logger.info("=== run_earnings_update start ===")
    try:
        result = update_calendar(ALL_US_STOCKS)
        logger.info(f"earnings calendar updated: {len(result or {})} entries")
        logger.info("=== run_earnings_update done ===")
    except Exception as e:
        logger.error(f"run_earnings_update crashed: {e}")


if __name__ == "__main__":
    main()
