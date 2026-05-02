# Phase 2 跨 Batch 待辦事項

> 這份檔案存放跨 batch、跨對話必須記住的設計決策與待辦。每個新對話啟動時請優先閱讀。

## Batch 11 (runners) 待辦

### run_trump_monitor.py 冷啟動保護
Trump CNN 鏡像 (https://ix.cnn.io/...) 含有 32,881 則歷史貼文。
第一次跑時 fetch_and_classify_new() 必須:
- 只處理「最近 24 小時」內的貼文(以 created_at 過濾)
- 舊貼文一次性標記進 trump_seen.json,但不推播
- 否則第一次跑會 Telegram 轟炸幾百則歷史 Tier 1 訊號

實作位置:src/runners/run_trump_monitor.py 入口
參考測試:Batch 3 已驗證 CNN 鏡像活著,32,881 則為實測數字

## 通用規則(已落實在 src/data/ 20 模組)

- 全部 import pandas_ta_classic as ta(注意底線)
- 所有外部 API fetcher 加 @tenacity.retry(3, exp backoff)
- ValueError / RuntimeError 不被 retry 吞,fail-fast
- 缺 API key 直接 raise(SEC_EDGAR_USER_AGENT、FRED_API_KEY)
- 冷啟動回 None 而非中性值(IVR、TSMC YoY、ETF flow)
- 全部 datetime 帶時區,絕對不用裸 datetime.now() 或 datetime.utcnow()

## 已知偏離但接受的決策

(Batch 1-3 累計 51 條偏離,簡述高影響力的)
- iv_rank max==min 回 None(不回 50)— 學習鎖 #2 安全性
- FRED_API_KEY / SEC_EDGAR_USER_AGENT 集中到 src/config/settings.py
- retry decorator 加 retry_if_not_exception_type 排除 ValueError/RuntimeError
- edgar identity 改 lazy init(避免 import 時連 SEC)
- rss_feeds._categorize 改用 set 交集(原 spec 邏輯反向)
- etf_flows 三層 fallback + SchemaError exception(原 spec 是 placeholder)

完整偏離記錄見 git log 與 commit message。

## 常見路徑(避免 Claude Code 記憶模糊)

- 持久化 state 統一寫到 `data_store/`(不是 data/state/、不是 state/)
- src.storage.state_manager 的 `read_json` / `write_json` 預設目錄就是 `data_store/`
- 已驗證寫入過的檔:
  - `data_store/distribution_days_log.json`(Batch 4)
  - `data_store/iv_history.json`(Batch 1)
  - `data_store/etf_flows_cache.json`(Batch 2)
  - `data_store/earnings_calendar.json`(Batch 2)
  - `data_store/fundamentals_snapshot.json`(Batch 2)
  - `data_store/trump_seen.json`(Batch 3)
  - `data_store/rss_seen.json`(Batch 3)
  - `data_store/tsmc_revenue_history.json`(Batch 3)

## Batch 7 後待重構

### LAYER0_SUBMODIFIER_RANGES 結構不一致
- 現況:LAYER0_SUBMODIFIER_RANGES["distribution_days"] = (-20, 0)(單一範圍)
- 但 v4 spec 規定 distribution 對 sell_call 是 +5(正向),不在範圍內
- Batch 5 暫時用 distribution.sell_call 獨立 (0, 10) 處理
- Batch 7 完成後重構:LAYER0_SUBMODIFIER_RANGES 改成 per-signal 結構
  例如 {"distribution_days": {"sell_call": (0, 10), "sell_put": (-15, 0), "leaps_entry": (-20, 0)}}
- 同步檢查其他 layer 是否有類似不一致

## Batch 8 完成時要重構

1. current_positions.py 實作後:
   - evaluate_all_exit_rules() 移除 try/except import 失敗 fallback
   - 改成正常 import,Batch 8 後不該再有 ImportError

2. hedge_dte_tracker.py + account_drawdown.py 實作後:
   - veto_checker 的 3 個 stub (lock_2 / lock_5 / lock_6) 從 context 讀真實值
   - context=None 的 fallback 拿掉
   - test_veto_checker.py 對應測試案例改成測「真實邏輯」而非 stub 行為

3. HARD_RULES 補:
   - min_hedge_dte_days: 45
   - max_drawdown_pct_for_new_leaps: -0.20
   - require_covered_for_short_call: True
   - 3 個 stub 改從 config 讀

## Phase 2 全部完成後重構

4. LAYER0_SUBMODIFIER_RANGES 改 per-signal 結構
   - 現況:LAYER0_SUBMODIFIER_RANGES["distribution_days"] = (-20, 0)
   - 應改:{"sell_call": (0, 10), "sell_put": (-15, 0), "leaps_entry": (-20, 0)}
   - 同步檢查其他 layer 的 sub-modifier 範圍是否有類似結構不一致
   - distribution.py 內 sell_call 獨立 (0, 10) 範圍移到 config

5. 重命名 `TWSTOCK_ACTIVE_ETF_RULES.tier1_single_etf_min_nav_pct`
   - 現況:鍵名 `_pct` 暗示「比例(0~1)」,但實際值 `0.01` 在 Batch 9 用作「百分點(1.0=1%)」
   - 應改:`tier1_single_etf_min_nav_diff_pp`(pp = percentage point,消除歧義)
   - 同步檢查 TWSTOCK_ACTIVE_ETF_RULES 其他鍵單位是否清楚

6. mock patch 路徑筆記:
   - 用 from X import Y 後,test 必須 patch 「本模組.Y」不是 「X.Y」
   - 這是 Python 標準行為(import 時綁定到本模組命名空間)
   - 例:test_veto_checker.py patch src.signals.veto_checker.is_earnings_within_days
     不是 src.data.earnings_calendar.is_earnings_within_days
