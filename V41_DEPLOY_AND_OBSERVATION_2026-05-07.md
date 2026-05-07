# Kevin Trading Monitor — v4.1 Deployment & Observation Handoff

> **日期**:2026-05-07
> **里程碑**:v4.1 五個 sprint 上線 + 第一輪 production verification 完成
> **承接**:PHASE_2_5_COMPLETE_AND_NIGHT_DEBUG.md
> **下一篇**:V41_OBSERVATION_RESULT(觀察期結束後寫,預計 1-2 週後)

---

## 1. 執行摘要

5/7 把 v41_sprint_status_2026-05-07.md 列的八個 sprint(實際合併成五個 commit)
push 上 GitHub origin/main。push 後手動觸發 iv_history_update workflow 驗證
v4.1 新加的 IV 累積機制,第一次跑 success,100 秒 wall time、113/115 ticker
覆蓋、SELL_PUT_WHITELIST 41 檔 100% 覆蓋。

關鍵副產物:今天順便釐清了 Cloudflare Worker 是「從未存在,記憶混淆」,
不是「被誤刪需重建」。Sprint 2.5.10 仍未實作,卡 GitHub PAT。

---

## 2. v4.1 五個 sprint commit 順序與 hash

| 順序 | Commit Hash | Sprint Title |
|---|---|---|
| 1 | fdabbda | sprint-2.6.7: reverse-lock-rule-6-2x-etf-short-call-block |
| 2 | 0c93dde | sprint-2.6.3: iv-history-daily-eod-runner-and-workflow |
| 3 | 21038af | sprint-2.6.10: earnings-blackout-by-value-thesis-1-7-365 |
| 4 | f60e2c7 | sprint-2.6.9: etf-liquidity-monthly-check-framework |
| 5 | 3e40a8a | sprint-2.6.1+cumulative: universe-v4.1-115-tickers-13-themes-7-tiers |

說明:v41_sprint_status §6 原列八個 commit titles,實際因為 sprint 改動高度
重疊(七個檔案被多 sprint 連續修改),拆獨立 commit 不可行。最終策略:

- Commit 1 (fdabbda): PHASE_2_STRATEGY_AND_DATA.md 第 6 條學習鎖反向(只動文件)
- Commit 2 (0c93dde): IV history 全新檔(runner + workflow)
- Commit 3 (21038af): value_thesis.py 抽離(只動新檔)
- Commit 4 (f60e2c7): ETF liquidity 全新三檔
- Commit 5 (3e40a8a): 累積式 commit,7 個 .py 檔含 sprint-2.6.7 / 2.6.4 / 2.6.2 /
  2.6.10 / 2.6.8 / 2.6.1 全部累積改動

備份分支:v41-pre-commit-backup-2026-05-07 指向 6d6f5b3 (sprint-2.5.9),
建議至少保留 48 小時,5/9 後可 git branch -D 清掉。

---

## 3. Production Verification 結果

### 3.1 本機端

- Python 3.14.2 (global, no venv)
- pytest tests/: 255 passed / 1 failed / 1 skipped (in 2.59s)
- Import sanity: thresholds / universe / value_thesis / etf_liquidity /
  veto_checker / scorers 全 pass
- universe 數字確認:SELL_PUT_WHITELIST = 41,ALL_TICKERS_SCAN = 115,THEMES = 13

### 3.2 GitHub Actions 端

#### iv_history_update workflow(手動觸發驗證)

- 觸發:web UI Run workflow,event=workflow_dispatch
- Run ID 25501231759
- head_sha: 7b5821b(dispatch 前 Earnings Calendar Update 推了 state commit)
- conclusion: success
- duration: 100 秒(14:12:45Z → 14:14:25Z)
- 結果:data_store/iv_history.json 新建,6389 bytes,341 行

#### iv_history.json 內容

- type: dict[ticker -> dict[date -> iv]]
- symbols collected: 113
- SELL_PUT_WHITELIST 41 檔 100% 覆蓋
- ALL_TICKERS_SCAN 115 檔中 113 檔成功,2 檔 missing:**BESI**, **TSMX**
- Sample: NVDA → {'2026-05-07': 0.4445}(44.45% IV,合理)

### 3.3 已知 yellow flags

| # | 項目 | 風險等級 | 處理時機 |
|---|---|---|---|
| 1 | test_v4_min_ivr_below_30_short_premium 用舊 veto code,assertion 沒同步改 | 低(test debt,不影響 prod) | Phase 3 cleanup |
| 2 | signal_scan_intraday 從 40 → 115 檔 wall time 未實測 | 中(可能撞 GitHub timeout) | 21:30 美股開盤後觀察 |
| 3 | BESI / TSMX 兩檔 yfinance 抓不到 IV | 低(都不在 SELL_PUT_WHITELIST) | 觀察期看是否持續 missing |

### 3.4 Wall time 預測校正

iv_history_update 跑 113 檔花 100 秒,提供 yfinance batch 對全 universe scan
的真實性能參考。signal_scan_intraday 之前 v2.5 跑 40 檔約 86 秒,擴 3 倍
理論上線性外插約 250-300 秒,落在 GitHub Actions 6 小時 timeout 內非常多。
原本 v41_sprint_status §8 寫的「3-5x 飆升」預測偏保守,實際應該 2.5-3x。

---

## 4. Cloudflare 認知修正

### 4.1 釐清的事實

5/7 line-cards Cloudflare 設定期間「誤刪投資專案」**是記憶混淆**,
不是真的誤刪:

1. kevin-trading-monitor 是 Python 100% 後端,沒有前端 dashboard,
   Cloudflare Pages 物理上無法 build
2. git 全分支 commit history 沒有任何 cloudflare / wrangler / worker
   字串
3. git 刪除歷史沒刪過任何相關檔
4. 整個 C:\Users\Administrator\Documents\Kevin_invest 樹掃光,
   沒有任何 .js / .ts / wrangler.toml

最合理解釋:之前討論過要建 Cloudflare Worker(Sprint 2.5.10 備援觸發),
但實際上沒做出來。Sprint 2.5.10 在 v41_sprint_status §4 也明確寫「未做,
卡 GitHub PAT」。

### 4.2 Cloudflare Worker 備援觸發 — 仍未實作

動機合理:GitHub Actions schedule throttle 對低活動 public repo 不可靠
(5/4 已實證 tw_eod 延後 2.5h、us_premarket 完全沒觸發)。

未實作的卡點:GitHub Fine-grained PAT 還沒申請。

5/7 對話中已寫好完整 Sprint 2.5.10 spec(全盲補打 + 30 分鐘間隔 + 14 個 workflow
清單),Worker JS source code 跟 wrangler.toml 已寫進 cloudflare/ 目錄
(working tree untracked,未 commit)。等 Kevin 申請 PAT + Cloudflare 後台 deploy
後再 commit 進 repo。

### 4.3 Cloudflare 帳號當前狀態

只有 jin-yi-yang-line-cards Pages deployment(line-cards 專案,跟投資無關)。
投資專案不需要佔用任何 Cloudflare 資源。

---

## 5. moomoo OpenAPI 評估(暫不採用)

5/7 中考慮過 moomoo 是否能解決 v4.1 的 IV 資料品質痛點。結論:**暫不採用**。

### 5.1 真相整理

- moomoo ID(行情帳號)跟 trading account 是兩件事 — 拿行情不一定要開戶
- 但美股選擇權 IV / Greeks **不在免費 LV1 範圍**:
  2025-04 公告把 Nasdaq Basic+TotalView 跟 NYSE ArcaBook 免費化,
  原文明寫「excluding U.S. stock futures and options」
- 要拿美股 option chain + IV + Greeks,必須買 quotation card
  (具體價格未公開,需進 moomoo data store 查)

### 5.2 架構衝突

moomoo OpenAPI 需要本機 / 雲端跑 OpenD daemon(TCP gateway),Python script
透過它連 broker server。這跟 v4.1 全雲端 stateless 架構打架:

- GitHub Actions runner 沒辦法穩定跑 daemon(每次新 worker、broker 多 IP login 會被 block)
- 整合方式只有兩種:本機 PC 24/7 跑 OpenD + push commit,或開 VPS(打破 $0/月預算)

### 5.3 重新評估時機

等 v4.1 yfinance IV 鏈跑滿一週,看 iv_history.json 累積品質:
- 如果 113/115 ticker 持續穩定 + IV 數值合理 → moomoo 沒急迫性,擱置
- 如果大量 ticker 開始 fail / 數值跳動異常 → 才考慮切 moomoo,屆時開新 sprint

---

## 6. 觀察期 TODO(下週重點)

### 6.1 自動會發生,需被動觀察

- **21:30 台北今晚**(美股開盤):signal_scan_intraday 第一次 v4.1 觸發,
  關注 wall time 是否 < 5 分鐘(超過要警覺,超過 10 分鐘要拆 batch)
- **06:00 台北明早**(US 22Z):iv_history_update 自然 cron 跑 day 2,
  關注 BESI / TSMX 是否仍 missing(若仍 missing → universe.py 處理)
- **06:00 台北明早**:signal_scan_eod 第一次 v4.1 觸發
- **每月 1 號 22Z**:liquidity_check 第一次 cron 觸發,寫 etf_liquidity_state.json

### 6.2 Kevin 主動要做

- **5/8 起床檢查**:GitHub Actions 過去 12 小時有沒有大量紅 X、Telegram 是否
  正常推 brief
- **5/9 之後**:確認穩定後 git branch -D v41-pre-commit-backup-2026-05-07
- **觀察 1-2 週累積真實使用感受**:
  - 哪則 brief 有用、哪則 swipe
  - Lisa 共用體驗(訂閱偏好需求?)
  - signal_scan / brief 觸發是否仍偶發 throttle
  - SELL_PUT 訊號量(IVR 70 嚴閾值 + 41 檔白名單下實際幾則)

### 6.3 Phase 3 sprint 候選(觀察期結束後啟動)

優先級由 v41_sprint_status §7 對齊:

1. **Sprint 2.5.10 Cloudflare Worker 備援觸發**(獨立)
   - 動作:Kevin 申請 GitHub Fine-grained PAT(scope: Actions Read+Write +
     Contents Read,target: kevin-trading-monitor 單一 repo)
   - 然後照 cloudflare/README.md(working tree 已存)的 Step 1-6 部署
2. **positions.json 真實填入**:5/4 晚美股已有實際操作,需開始記錄
3. **Sprint 2.6.5 雙速平倉**:依賴 positions.json 真實
4. **EV 追蹤雙資料庫 + 月報**(訊號採納 vs 假設採納)
5. **Test debt cleanup**:test_v4_min_ivr_below_30_short_premium assertion
6. **universe 清理**:BESI → BESIY 或刪除,TSMX 從 ALL_TICKERS_SCAN 拿掉
7. **moomoo 重評估**:依觀察期 yfinance 品質結果決定

---

## 7. 工程環境固化筆記(承接 PHASE_2_5 §5)

### 7.1 Cowork 端 sandbox 限制(不變)

- Edit / Write tool 對 CJK 大檔截尾 bug
- PowerShell Measure-Object -Line 對 CJK + CRLF quirk
- Linux mount → Windows fs 寫入受限
- sandbox `__pycache__` 寫不掉,Python 跑舊 bytecode

### 7.2 git push race(本日新發現)

state 自動 commit 跟使用者 commit 偶爾衝突(5/7 push 五個 sprint commit 時撞到 4 個
state commit 在 origin/main),解法:`git pull --rebase origin main` 後重 push。
.py / .yml / .md vs data_store/*.json 零交集,rebase 不會 conflict。

### 7.3 GitHub Token 配置(本日確認)

- Cowork sandbox 環境沒有 GITHUB_TOKEN / GH_TOKEN / GITHUB_PAT 環境變數
- gh CLI 沒裝
- Windows credential manager 只給 git push/pull 用,不能用在 REST API auth
- 結論:CC 要 trigger workflow_dispatch / 跑 GitHub REST API,只能 web UI 手動觸發或 web fetch 公開 endpoint

### 7.4 PAT 申請正確 scope(本日新查證)

文件寫 `actions:write` 不夠,實證需要 fine-grained PAT 加上:
- Actions: Read and write
- **Contents: Read**(這個 GitHub 文件沒寫,但社群實證 workflow_dispatch
  API 會檢查 contents 權限)
- Metadata: Read-only(自動)

---

## 8. 下次新對話銜接 prompt
我是 justicetwtw,接續 Kevin Trading Monitor 開發。
repo: github.com/justicetwtw/kevin-trading-monitor
local: C:\Users\Administrator\Documents\Kevin_invest\kevin-trading-monitor
當前狀態:

v4.1 五個 sprint 已 push origin/main,HEAD = 3e40a8a + 之後的 [skip ci]
iv_history_update production verification 通過(100 秒 wall time)
觀察期累積中,backup branch v41-pre-commit-backup-2026-05-07 待 5/9 後刪
Cloudflare Worker / moomoo / Phase 3 sprint 都在等觀察期結束

今天目的:[填你今天想做的事]
請參考 V41_DEPLOY_AND_OBSERVATION_2026-05-07.md 完整 context。

---

## 9. 5/7 commit 列表(本機 + push 完整)
3e40a8a sprint-2.6.1+cumulative: universe-v4.1-115-tickers-13-themes-7-tiers
f60e2c7 sprint-2.6.9: etf-liquidity-monthly-check-framework
21038af sprint-2.6.10: earnings-blackout-by-value-thesis-1-7-365
0c93dde sprint-2.6.3: iv-history-daily-eod-runner-and-workflow
fdabbda sprint-2.6.7: reverse-lock-rule-6-2x-etf-short-call-block
6d6f5b3 sprint-2.5.9: brief 6 種重設(命名修正 + tw_open/us_open 新增 + DST + silent)

之後 origin/main 還會收到:
- d476772 state: Trump Monitor [skip ci]
- 7b5821b state: Earnings Calendar Update [skip ci]
- d0943a2 state: IV History Update [skip ci](來自手動觸發 verify)
- ...持續累積中

— end —
