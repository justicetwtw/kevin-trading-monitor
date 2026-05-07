"""IV history 每日 EOD 累積 (Sprint 2.6.3 / v4.1)。

每個美股工作日盤後跑,把 ALL_TICKERS_SCAN 每檔的當日 ATM IV 寫入
data_store/iv_history.json,供 calc_iv_rank 計算 IVR / IVP 用。

實作說明:
- update_iv_history(symbol) 已存在於 src.data.iv_rank,內部抓 ATM IV +
  寫檔 + 保留 300 天歷史。本 runner 僅做 ticker 迴圈 + 失敗隔離。
- 單一 ticker 抓不到 IV(yfinance 偶爾失敗,項目指令 §7-E)不中斷 batch,
  log warn 後繼續。
- 美國假日 cron 仍會跑,但 get_atm_iv 會回 None,update_iv_history
  直接 return 不寫,無副作用。
- 累積到 MIN_SAMPLES_FOR_RANK = 30 天才會開始出 IVR。

cron:0 22 * * 1-5 (UTC) = 美東 17:00 (EST) / 18:00 (EDT),收盤後 1 小時。
"""

from loguru import logger

from src.config.universe import ALL_TICKERS_SCAN
from src.data.iv_rank import update_iv_history


def main() -> None:
    total = len(ALL_TICKERS_SCAN)
    logger.info(f"=== run_iv_history_update start (tickers={total}) ===")
    success = 0
    failed: list[str] = []
    for sym in ALL_TICKERS_SCAN:
        try:
            update_iv_history(sym)
            success += 1
        except Exception as e:
            logger.warning(f"update_iv_history({sym}) failed: {e}")
            failed.append(sym)
    logger.info(
        f"=== run_iv_history_update done: success={success}/{total}, "
        f"failed={len(failed)} ==="
    )
    if failed:
        logger.warning(f"failed tickers: {failed}")


if __name__ == "__main__":
    main()
