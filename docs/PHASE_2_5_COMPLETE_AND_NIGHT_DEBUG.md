# Phase 2.5 系列正式收工 + 5/4 production debug 完整紀錄

> **時間**:2026/05/04 全天 + 入夜
> **工時**:14+ 小時 production debug + iteration
> **結果**:Phase 2.5 系列(2.5 / 2.5.2 / 2.5.3 / 2.5.5+6 / 2.5.7)全部 production-ready

---

## 1. 今天系統最終狀態
總規模:

80+ src 檔
222 unit tests passed (1 skipped)
15 GitHub Actions workflows + 1 composite action
約 14,800 行 production Python
$0/月運行成本
一個人 + 老婆 + Claude Max 5x

夫妻共用 production-ready ✅

## 2. 今天完成的所有 Phase
Phase 2.5    : 4 次 daily brief (trader 視角第一版)
Phase 2.5.2  : investor 視角大改版(打折買 / 鎖利出 / 深度便宜買)
Phase 2.5.3  : brief_type schedule 字串 robust to delay
Phase 2.5.5  : 雙時間 cron + dedup + sanity check
Phase 2.5.6  : 夏令時間修正(us_premarket_to_intraday / us_midday_to_afterhours)
Phase 2.5.7  : 多 chat_id + httpx hotfix(夫妻共用)

## 3. 今天踩到的真實 production bug 列表

### Bug 1:GitHub schedule throttle(平台問題)
- 5/4 13:30 tw_eod 延後到 16:05 觸發(2.5h delay)
- 5/4 21:00 us_premarket 完全沒觸發
- 解法:Phase 2.5.5 雙時間 cron + dedup
- 教訓:GitHub Actions schedule 對低活動 repo 不可靠,要冗餘設計

### Bug 2:brief_type wallclock 偵測 fallback
- 延後觸發時 HOUR=08 落入 fallback us_eod,推錯 brief 種類
- 解法:Phase 2.5.3 改用 github.event.schedule cron 字串判斷

### Bug 3:夏令時間 cron 設計缺陷
- us_premarket 21:00 台北 = 夏令時間美股開盤前 30 分鐘(原意 1.5h)
- us_midday 06:00 台北 = 夏令時間已收盤 2 小時(原意盤中)
- 解法:Phase 2.5.6 加 DST detection + 兩個 brief 變體

### Bug 4:GitHub Secrets 改格式但雲端跑舊版 → 推送 timeout
- TELEGRAM_CHAT_ID 改逗號分隔,但舊版整串當單一 chat_id 送
- Telegram API 拒絕 → PTB library 包成「Timed out」誤導性錯誤
- 解法:Phase 2.5.7 多 chat_id 解析 + httpx 取代 PTB

## 4. 關鍵發現 / 學習

### 4.1 GitHub Actions debug 工具鏈
- gh CLI 沒裝
- PowerShell Invoke-RestMethod 打 GitHub public API(60/hr 配額,夠用)
- Web Telegram 取代手機方便複製 token
- Phase 3 之前可考慮裝 gh CLI 一勞永逸

### 4.2 Token 處理的真實風險
- BotFather token 容易只複製到後半段(漏前面數字+冒號)
- 永遠先用 getMe 驗證 token 對不對
- Token 只貼到 PowerShell 環境變數,不貼到 Claude Code 對話

### 4.3 Hotfix 規格寫作的失誤
- 沒在 commit 規格內加「working tree backup」,導致 Phase 2.5.2 上一輪本機改動消失
- 沒在新 session 開頭要求 git status / git log 對齊
- 未來規格應加:git status + git log -3 對齊狀態 / 改動前 stash 備份 / commit 前明確列出檔案清單

### 4.4 Lisa 加入後系統行為變化
- 所有訊息(brief / signal / Trump alert / sanity)都同時推給 Kevin + Lisa
- 預期 Lisa 心理準備:可能半夜收到 Trump tier1 alert / 凌晨美股 brief
- Phase 4+ 考慮:訂閱偏好(Lisa 只看 brief 不看 Trump)

## 5. Phase 2.5.2 Brief 真實成果

### Investor 視角 brief 結構

#### us_eod (台北 08:30 / 09:00)
- 整體環境(SPY/QQQ/VIX + Layer 0 三維 modifier)
- Sell PUT 機會檢視(top 3,「離接貨區還多遠」)
- Sell CALL 機會檢視(持倉空時跳過)
- LEAPS 進場檢視(top 3)
- 部位健康度(持倉空時跳過)
- 今日事件

#### tw_eod (台北 13:30 / 14:00)
- 台股當日(00631L + 2330)
- 加碼條件檢視(距 52W 高 / 週 RSI vs A/B/C 級門檻)
- 主動 ETF 動向
- 美股盤前展望(ES futures + TSM ADR 推估 2330)

#### us_premarket (台北 21:00 / 21:30)
- 整體環境
- Pre-market 異動 (>2%)
- Sell PUT / LEAPS top 3
- 今日事件

#### us_midday (台北 06:00 / 06:30)
- 整體環境
- Sell PUT / LEAPS top 3

#### us_premarket_to_intraday (DST 變體)
- 標題改「美股開盤即時 brief」
- 「Pre-market 異動」改「開盤即時異動」
- 結尾加 DST 警告

#### us_midday_to_afterhours (DST 變體)
- 標題改「美股盤後早晨 brief」
- 新增「美股當日完整收盤」段(SPY/QQQ/DIA/VIX)
- 結尾加 DST 警告

### Brief 結論句 logic
動態根據 fully_met / partial_met / none_met:
- 全達:「[symbols] 條件齊備,強烈候選」
- 部分達:「[symbols] 接近接貨區,等 RSI 過低」+ 缺什麼分析
- 全未達:「全 universe 距條件仍遠,等市場回檔」
- IVR 全 n/a 時加 Phase 3 IV 累積待辦提示

## 6. Phase 3 已知待辦(Phase 2 + 2.5 設計缺陷)

### 6.1 IV history 累積(必須做)
問題:data_store/iv_history.json 沒人寫入 → IVR 永遠 n/a → Sell PUT / LEAPS 訊號的 IVR 條件永遠失能

Phase 3 方案:
- 新增 src/runners/run_iv_history_update.py
- 每日 EOD 後對 SELL_PUT_WHITELIST 抓 IV 寫入 history
- 累積 ≥30 天後 IVR 才有意義
- 對應 .github/workflows/iv_history_update.yml

### 6.2 EV 追蹤雙資料庫
- signal_outcomes_assumed.parquet:所有 ≥70 訊號都假設採納
- signal_outcomes_actual.parquet:Telegram inline button 標記實際採納
- 月度報告:勝率、EV、Layer 0 modifier 影響、假設 vs 實際對比

### 6.3 部位實際填入
- 目前 positions.json 是 mode_2 但全部 _example
- 5/4 晚有實際美股操作,該開始填真實部位
- LEAPS / 現股 / 短期選擇權都要記
- 啟動部位健康度模組(LEAPS 損益 / Short Delta / 對沖 DTE / 帳戶回撤)

### 6.4 us_premarket_to_intraday「今日事件」段位置優化
- 現在沿用 us_premarket 結構,財報 T-0 對開盤後 brief 意義略低

### 6.5 GitHub Actions push race
- state commit 跟使用者 commit 偶爾衝突,要 stash + rebase
- Phase 3 可考慮用 GitHub Cache 替代 git commit state

### 6.6 環境工具升級
- 裝 gh CLI(debug 速度+++)
- requirements.txt 移除 python-telegram-bot 依賴

## 7. Phase 3 開工前的觀察期任務(下週重點)

### 7.1 累積真實 brief 使用感受
- 哪則 brief 你會仔細看
- 哪則直接 swipe
- 「等 RSI 過低」結論句對你有用嗎
- 「TSM × 0.7~1.0 推估 2330」這個推算對決策有用嗎

### 7.2 累積夫妻共用使用感受
- Lisa 收到後反應如何
- 哪些訊息 Lisa 完全不需要(Phase 4 訂閱偏好)
- 推送頻率夫妻能接受嗎

### 7.3 累積系統可靠性數據
- GitHub schedule throttle 一週發生幾次
- Sanity check 警告觸發幾次
- DST 變體實際觸發幾次
- 哪個 brief 種類延後最頻繁

### 7.4 美股實際操作 → 訊號 vs 行動 vs 結果記錄
- 5/4 晚美股有操作,記錄方式:
  - 操作日期 / ticker / 動作(buy/sell/sell put/sell call/leaps)
  - 系統當時推什麼訊號(分數)
  - 為什麼操作(thesis)
  - 操作當下價格 / strike / DTE
  - 結果(7 天 / 14 天 / 30 天追蹤)
- 這些是 Phase 3 EV 追蹤的種子資料

## 8. 下次開工 Phase 3 規格(下週起點)

### 8.1 Phase 3 第一個 batch 候選
- IV history 累積(解 IVR 永遠 n/a)
- EV 追蹤基礎設施(雙 parquet + 月報)
- positions.json 真實填入 + 部位健康度啟動

### 8.2 觀察期數據累積策略
建議累積 1-2 週真實使用數據後再開 Phase 3,理由:
- 知道哪則 brief 真有用
- 知道延後 / 漏推真實頻率
- 累積首批訊號 vs 操作 vs 結果樣本

## 9. 5/4 晚美股操作記錄 placeholder
2026/05/04 (台北深夜 / 美股盤中)
操作 1:
Ticker:
動作:
價格 / strike / DTE:
系統訊號(若有):
Thesis:
操作 2:
...
備註:

系統還沒 Phase 3 EV 追蹤,先用文字記錄
1-2 週後實作 EV 追蹤時這份紀錄是種子資料


## 10. 5/4 commit 列表(已 push 到 origin/main)
Phase 2.5     (8197279)  Phase 2.5: 4 brief 第一版
Phase 2.5.2   (42298c3)  Investor 視角大改版
Phase 2.5.3   (2bd0ced)  brief_type schedule 字串
Phase 2.5.5+6 (2bdbec9)  雙時間 cron + dedup + sanity + DST
Phase 2.5.7+hotfix       Telegram 多人 + httpx 取代 PTB

## 11. 下次新對話開頭 prompt template
我是 justicetwtw,接續 Kevin Trading Monitor 開發。
repo: github.com/justicetwtw/kevin-trading-monitor
local: C:\Users\Administrator\Documents\Kevin_invest\kevin-trading-monitor
chat_ids: Kevin 1581126208, Lisa 8773385365(夫妻共用)
當前狀態:

Phase 2.5 系列已完工,production-ready
Phase 3 待開工(IV history / EV 追蹤 / positions 填入)
觀察期累積真實使用感受中

今天目的:[填你今天想做的事]
請參考 docs/PHASE_2_5_COMPLETE_AND_NIGHT_DEBUG.md 完整 context。
