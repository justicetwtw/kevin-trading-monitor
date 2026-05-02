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
