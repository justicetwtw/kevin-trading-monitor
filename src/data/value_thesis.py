"""value_thesis 讀取(v4.1 共用模組)。

從 data_store/universe_with_thesis.json 讀 ticker 的 value_thesis 標籤。
五級:deep_value / fair_value / expensive / review / exit。

v4.1 用途:
- veto_checker.check_lock_earnings_blackout: 動態財報窗期
- leaps_entry_scorer: LEAPS 進場 thesis 過濾
- exit_rules: 出場規則例外處理
- 雙速平倉(2.6.5 待做):快慢線閾值依 thesis 調整

抽出此模組是為了避開循環依賴(veto_checker 不能 import leaps_entry_scorer,
因為 leaps_entry_scorer 已 import check_all_hard_rules from veto_checker)。
"""

import json

from loguru import logger

from src.storage.state_manager import DATA_STORE_DIR

UNIVERSE_THESIS_PATH = DATA_STORE_DIR / "universe_with_thesis.json"

VALID_THESIS_RATINGS = ("deep_value", "fair_value", "expensive", "review", "exit")


def get_value_thesis(symbol: str) -> str:
    """讀 universe_with_thesis.json 取 value_thesis。預設 'fair_value'。

    回傳值保證在 VALID_THESIS_RATINGS 內,讀失敗或標籤異常都回 fair_value。
    """
    if not UNIVERSE_THESIS_PATH.exists():
        return "fair_value"
    try:
        with open(UNIVERSE_THESIS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        rating = (
            data.get("tickers", {})
            .get(symbol, {})
            .get("value_thesis", {})
            .get("rating", "fair_value")
        )
        if rating not in VALID_THESIS_RATINGS:
            logger.warning(
                f"unknown value_thesis '{rating}' for {symbol}, fallback fair_value"
            )
            return "fair_value"
        return rating
    except Exception as e:
        logger.warning(f"value_thesis read failed for {symbol}: {e}")
        return "fair_value"
