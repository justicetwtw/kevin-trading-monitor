# Context: GitHub Actions（排程與 Secrets）

> 來源：直接讀 `.github/workflows/*.yml` 與 `.github/actions/commit-state/action.yml`（已查證）。
> **紅線**：不得擅改 workflow 的排程、觸發條件或步驟行為（`AGENTS.md` §4.2）。本檔是對照表，不是改它的許可。

## 1. 共通模式

- 全部跑 `ubuntu-latest` + Python 3.11，`pip install -r requirements.txt`。
- 全部支援 `workflow_dispatch`（手動觸發）+ `schedule`（cron，UTC）。
- 進入點一律 `python -m src.runners.run_*`。
- 多數 workflow 末端呼叫 `commit-state` 複合 action，把 `data_store/` 變動 commit + push（見 §4）。
- cron 註解中的「台北時間」= UTC+8。

## 2. 20 個 Workflow 對照表

| Workflow (name) | 檔案 | cron (UTC) | Runner | Secrets |
|---|---|---|---|---|
| Trump Monitor | `trump_monitor.yml` | `*/5 * * * *`（每 5 分）| `run_trump_monitor` | TELEGRAM_* |
| News Monitor | `news_monitor.yml` | `*/10 * * * *`（每 10 分）| `run_news_monitor` | TELEGRAM_* |
| SEC EDGAR Monitor | `sec_monitor.yml` | `15 * * * *`（每時 15 分）| `run_sec_monitor` | TELEGRAM_*, SEC_EDGAR_USER_AGENT |
| Signal Scan Intraday | `signal_scan_intraday.yml` | `*/15 13-22 * * 1-5` | `run_signal_scan_intraday` | TELEGRAM_*, FRED_API_KEY |
| Signal Scan EOD | `signal_scan_eod.yml` | `15 21 * * 1-5` | `run_signal_scan_eod` | TELEGRAM_*, FRED_API_KEY |
| Market Brief | `market_brief.yml` | 多組（見 §3，含 DST 主/備）| `run_market_brief` | TELEGRAM_*, FRED_API_KEY |
| Brief Sanity Check | `brief_sanity.yml` | `0 15 * * *` + `30 15 * * *`（台北 23:00 / 23:30）| `run_brief_sanity` | TELEGRAM_* |
| Macro Layer Update | `macro_layer.yml` | `30 22 * * 1-5` | `run_macro_layer` | FRED_API_KEY |
| Institutional & Insider Scan | `institutional_scan.yml` | `0 23 * * 1-5` | `run_institutional_scan` | SEC_EDGAR_USER_AGENT |
| Position Management Check | `position_check.yml` | `0 22 * * 1-5` | `run_position_check` | TELEGRAM_* |
| IV History Update | `iv_history_update.yml` | `0 22 * * 1-5` | `run_iv_history_update` | —（無）|
| Earnings Calendar Update | `earnings_update.yml` | `0 12 * * *` | `run_earnings_update` | —（無）|
| ETF Liquidity Monthly Check | `liquidity_check.yml` | `0 22 1 * *`（每月 1 號）| `run_liquidity_check` | —（無）|
| AAII Sentiment Update | `aaii_update.yml` | `0 22 * * 4`（週四）| `run_aaii_update` | —（無）|
| TSMC Monthly Revenue | `tsmc_revenue.yml` | `0 8 10 * *`（每月 10 號）| `run_tsmc_revenue` | TELEGRAM_* |
| Taiwan Stock Signal Scan | `twstock_signal.yml` | `30 6 * * 1-5`（台北 14:30）| `run_twstock_signal` | TELEGRAM_* |
| Health Check | `health_check.yml` | `0 9 * * 1`（週一）| `run_health_check` | TELEGRAM_* |
| Active ETF Consensus Digest | `active_etf_digest.yml` | `0 10 * * 1-5` | `run_active_etf_digest` | GMAIL_SENDER, GMAIL_APP_PASSWORD, EMAIL_RECIPIENT |
| Dashboard Build | `dashboard_build.yml` | `30 23 * * 1-5` + `30 6 * * 1-5`（台北 07:30 / 14:30）| `run_dashboard_build` | —（無）|
| Gooaye Digest | `gooaye_digest.yml` | `*/30 * * * *`（每 30 分輪詢，dedup 使多數 run no-op）| `run_gooaye_digest` | GEMINI_API_KEY, GEMINI_MODEL, GMAIL_*, EMAIL_RECIPIENT |

> `TELEGRAM_*` = `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`；`GMAIL_*` = `GMAIL_SENDER` + `GMAIL_APP_PASSWORD`。
> 註：`health_check.yml` 與 `brief_sanity.yml` **不**呼叫 `commit-state`（不產生 state 變動）。

## 3. Market Brief 的 DST 排程（特別複雜）

`market_brief.yml` 有約 20 條 cron（主 + 備各成對），涵蓋 6 種 brief。美股相關時段分**夏令 / 冬令兩套**，由 `settings.py: is_us_dst_active()` 在 runner 內 gating，避免 GitHub schedule 在 DST 切換時推錯 brief 種類。台股 brief（`tw_open` / `tw_close`）為固定時間。**要看確切對照，讀 `market_brief.yml` 內每條 cron 的註解**，不要憑記憶複述。

## 4. `commit-state` 複合 action

`.github/actions/commit-state/action.yml`：

1. 設 `github-actions[bot]` 身份，`git add data_store/`。
2. 無變動 → 直接結束。
3. 有變動 → commit 訊息 `state: {workflow} [skip ci]`（`[skip ci]` 防止 state commit 觸發新一輪 workflow）。
4. push 失敗時 `git pull --rebase origin main` 後重試，最多 3 次（處理多 workflow 並行 push race）。

這就是為什麼 `git log` 充滿 `state: ... [skip ci]` commit——它們是自動產物，不是人手改動。

## 5. 已知平台限制（背景知識，來自 handoffs）

- **GitHub schedule throttle**：低活動 public repo 的排程觸發**不保證準時**（曾有延後數小時或漏觸發）。系統用「主 + 備雙 cron」+ 去重 + `brief_sanity` 來冗餘補償。所以看到某 brief 晚到 / 偶爾沒到，**先懷疑平台 throttle，而非程式 bug**。
- 曾規劃 Cloudflare Worker 作備援觸發（Sprint 2.5.10），**截至最新 handoff 仍未實作**（卡 GitHub PAT）。除非使用者明說要做，不要當它已存在。

## 6. 紅線

- 不改任何 cron、觸發條件、步驟、secret 注入方式。
- 不在 workflow 加入會觸發收費服務的步驟。
- 要新增 / 調整排程一律先與使用者確認，並走 feature branch + PR。
