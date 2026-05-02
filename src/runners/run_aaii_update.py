"""AAII 散戶情緒週更新 (每週四 cron)。

⚠ Section 12.10 spec 寫 update_aaii_sentiment() 不存在 → 改用 classify_aaii()(已寫 state)。
"""

from loguru import logger

from src.layers.aaii_sentiment import classify_aaii


def main() -> None:
    logger.info("=== run_aaii_update start ===")
    try:
        result = classify_aaii() or {}
        logger.info(
            f"AAII updated: regime={result.get('regime')} "
            f"modifier={result.get('modifier')}"
        )
        logger.info("=== run_aaii_update done ===")
    except Exception as e:
        logger.error(f"run_aaii_update crashed: {e}")


if __name__ == "__main__":
    main()
