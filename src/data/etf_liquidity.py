"""ETF 選擇權流動性檢查(Sprint 2.6.9 / v4.1)。

v4.1 §2.2 主題 ETF Tier F 動態檢查:月選擇權成交量 > 10k 自動升 Tier E,
< 10k 維持 Tier F。

設計權衡:yfinance 沒直接提供「月選擇權成交量」API。本模組改用
`openInterest`(未平倉合約)加總當代理 — 比 daily volume 穩定,代表持續
流動性。閾值同 v4.1 spec(10k),但實際是 OI 而非 monthly volume。

Hysteresis(避免 Tier 月月切):
- 從 F 升 E:OI ≥ 12000
- 從 E 降 F:OI < 8000
- 8000 ≤ OI < 12000:保持上次狀態
- 冷啟動(無 prev_tier):用 10000 當 cutoff
"""

from typing import Optional

import yfinance as yf
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

LIQUIDITY_HYSTERESIS_UP = 12000     # 從 F 升 E 門檻
LIQUIDITY_HYSTERESIS_DOWN = 8000    # 從 E 降 F 門檻
LIQUIDITY_COLD_START_CUTOFF = 10000 # 冷啟動門檻
EXPIRY_SAMPLE_COUNT = 3             # 取前 N 個 expiry 加總 OI(代表近月流動性)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_etf_liquidity_proxy(symbol: str) -> Optional[int]:
    """抓 ETF 選擇權流動性代理(前 N 個 expiry 的 calls+puts openInterest 加總)。

    回傳:
        int: 加總 openInterest
        None: 該 symbol 沒選擇權 / API 失敗
    """
    try:
        ticker = yf.Ticker(symbol)
        if not ticker.options:
            return None
        total_oi = 0
        for exp in ticker.options[:EXPIRY_SAMPLE_COUNT]:
            try:
                chain = ticker.option_chain(exp)
                total_oi += int(chain.calls["openInterest"].fillna(0).sum())
                total_oi += int(chain.puts["openInterest"].fillna(0).sum())
            except Exception as inner:
                logger.warning(
                    f"fetch_etf_liquidity_proxy({symbol}) inner expiry {exp} failed: {inner}"
                )
                continue
        return total_oi
    except Exception as e:
        logger.error(f"fetch_etf_liquidity_proxy({symbol}) failed: {e}")
        return None


def classify_liquidity_tier(current_oi: Optional[int], prev_tier: Optional[str] = None) -> str:
    """配 hysteresis 判定 Tier E vs F。

    參數:
        current_oi: 當前流動性代理值(openInterest 加總),None 表抓不到
        prev_tier: 上次的 Tier("E" / "F" / None=冷啟動)

    回傳:
        "E" 或 "F"

    冷啟動規則:current_oi None 或 prev_tier None → 用 10000 cutoff(保守)
    """
    if current_oi is None:
        # 抓不到資料:保留上次 Tier(若無則保守 F)
        return prev_tier if prev_tier in ("E", "F") else "F"

    if prev_tier == "E":
        return "E" if current_oi >= LIQUIDITY_HYSTERESIS_DOWN else "F"
    if prev_tier == "F":
        return "E" if current_oi >= LIQUIDITY_HYSTERESIS_UP else "F"
    # cold start
    return "E" if current_oi >= LIQUIDITY_COLD_START_CUTOFF else "F"
