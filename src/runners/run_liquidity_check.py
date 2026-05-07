"""ETF 流動性月度檢查(Sprint 2.6.9 / v4.1)。

每月 1 號 cron,跑 universe 內所有 ETF 的選擇權流動性代理,寫
data_store/etf_liquidity_state.json。Tier 升降配 hysteresis(升 12k / 降 8k)。

對象來源:
- ETF_HEDGE(SPY/QQQ/SMH/SOXL)
- ETF_LEVERAGED_INDEX(QLD/SSO)
- ETF_LEVERAGED_SINGLE_STOCK(NVDL/AMDL/...)
- (Sprint 2.6.1 上線後自動納入主題 ETF:PPA/UFO/URNM/...)

State schema:
{
  "last_updated": "YYYY-MM-DD",
  "tickers": {
    "SPY": {"oi": 1234567, "tier": "E"},
    "PPA": {"oi": 8500,    "tier": "F"}
  }
}

降 / 升 Tier 都會 log warn(Kevin 後續視訊號變動接手)。
"""

from datetime import datetime

from loguru import logger

from src.config.settings import TIMEZONE_US_MARKET
from src.config.universe import (
    ETF_HEDGE,
    ETF_LEVERAGED_INDEX,
    ETF_LEVERAGED_SINGLE_STOCK,
    ETF_THEMATIC,
)
from src.data.etf_liquidity import (
    classify_liquidity_tier,
    fetch_etf_liquidity_proxy,
)
from src.storage.state_manager import read_json, write_json

LIQUIDITY_STATE_FILE = "etf_liquidity_state.json"


def _collect_etf_universe() -> list[str]:
    """匯總所有要檢查流動性的 ETF symbol。"""
    syms: list[str] = []
    syms.extend(ETF_HEDGE)
    syms.extend(ETF_LEVERAGED_INDEX)
    syms.extend(ETF_LEVERAGED_SINGLE_STOCK.keys())
    syms.extend(ETF_THEMATIC)  # v4.1 主題 ETF(動態升降 E/F)
    # 去重保留順序
    seen: set[str] = set()
    unique: list[str] = []
    for s in syms:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return unique


def main() -> None:
    etfs = _collect_etf_universe()
    total = len(etfs)
    logger.info(f"=== run_liquidity_check start (etfs={total}) ===")

    prev_state = read_json(LIQUIDITY_STATE_FILE, default={})
    prev_tickers = prev_state.get("tickers", {})

    today = datetime.now(TIMEZONE_US_MARKET).strftime("%Y-%m-%d")
    new_state: dict = {"last_updated": today, "tickers": {}}

    transitions: list[str] = []
    for sym in etfs:
        oi = fetch_etf_liquidity_proxy(sym)
        prev_tier = prev_tickers.get(sym, {}).get("tier")
        new_tier = classify_liquidity_tier(oi, prev_tier)
        new_state["tickers"][sym] = {"oi": oi, "tier": new_tier}

        if prev_tier and prev_tier != new_tier:
            msg = f"{sym}: tier {prev_tier} -> {new_tier} (oi={oi})"
            logger.warning(msg)
            transitions.append(msg)

    write_json(LIQUIDITY_STATE_FILE, new_state)
    logger.info(
        f"=== run_liquidity_check done: total={total}, "
        f"transitions={len(transitions)} ==="
    )
    if transitions:
        logger.warning(f"tier transitions: {transitions}")


if __name__ == "__main__":
    main()
