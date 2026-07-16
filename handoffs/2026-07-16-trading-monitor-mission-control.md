# Kevin Trading Monitor — Mission Control & Private Portfolio Risk Handoff

> **日期**: 2026-07-16  
> **里程碑**: Trading Monitor 從被動訊號 dump 改造成 thesis-first Mission Control，並補齊安全私有部位監控基礎  
> **承接**: `2026-05-07-v41-deploy-and-observation.md`  
> **下一篇**: production activation / correlated exposure / opportunity-ranking observation

---

## 1. 執行摘要

本次針對「Trading Monitor 基本上無作用」做 fresh-context 對抗式檢查，不只改 UI，而是沿 dashboard → position input → PnL → routing → persistence → logs → workflow exit status 全鏈追查。

結果確認多個會讓系統「看似有跑、實際無效」的根因：雲端只讀得到公開範本、drawdown 欄位名錯誤、LEAPS 單位差 100 倍、position alert 被分類到不推送的 P2、帳戶值明文落在 public repo、例外被吞後 Actions 假綠燈，以及 partial valuation 可能污染 drawdown。

上述 P0/P1 foundation 已集中在 draft PR #7。新系統現在具備：

- exceptions-first Mission Control
- theme / thesis / allocation context
- GitHub Actions secret 私有部位輸入
- private Telegram portfolio risk brief
- 可推送的 LEAPS / short-delta / hedge-DTE alerts
- encrypted / redacted / opaque public state
- degraded workflow fail-closed
- optional GitHub Pages deployment path

仍未 merge；production activation 需要 repository owner 親自在 GitHub 設定 secrets / variable / Pages，agent 不接收任何實際值。

---

## 2. GitHub 狀態

- Epic: #6 — `Epic: turn Trading Monitor into a thesis-first capital allocation system`
- Branch: `agent/trading-monitor-mission-control`
- Draft PR: #7 — `feat: turn dashboard into thesis-first Trading Mission Control`
- Base at PR creation: `main` / `304967484b788d6e4d176579636f084880b2a3c0`
- PR scope at last check: 32+ files; one coherent vertical slice covering public dashboard, private monitoring, privacy, reliability, tests and docs
- Merge policy: do not merge until final CI is green and owner explicitly approves

---

## 3. 主要根因與修正

### 3.1 雲端沒有真實部位

原本 `position_check.yml` 只能讀 public `data_store/positions.json`，但文件又明確禁止 commit 真實部位，因此 production 永遠只能看到範本。

修正：

- 新增 `POSITIONS_JSON` Actions secret runtime input
- secret 優先於 local file
- strict schema validation
- malformed present secret fail closed，不 fallback public file
- public snapshot 只留 aggregate health

### 3.2 Drawdown 根本沒執行

`run_position_check.py` 讀 `snapshot["total_value"]`，實際 snapshot 欄位是 `total_estimated_value`。

修正後使用正確欄位；且只有完整估值時才更新 drawdown。

### 3.3 LEAPS PnL 差 100 倍

Black–Scholes 回傳 per-share premium，schema 的 `cost_per_contract` 是 premium ×100；舊 code 直接比較，正常部位可能被誤算接近 -99%。

修正後統一使用 whole-contract USD，並有 dedicated regression tests。

### 3.4 Position alerts 被 router 靜默丟棄

舊 runner 預設 `yellow`，router 將 yellow 分到 P2；P2/P3 按設計不推 Telegram。

修正：

- LEAPS / short-delta / hedge-DTE exceptions → P1
- severe LEAPS trigger → orange P1
- major drawdown 仍由既有 P0 規則處理

### 3.5 Public repo 洩漏風險

原本可能洩漏：

- `drawdown_history.json` plaintext peak/current
- dedup/routing key 的 symbol
- Telegram public Actions log 前 50 字
- legacy `leaps_exposure.json` contract detail
- third-party market-data library raw logs

修正：

- `POSITION_STATE_KEY` Fernet encryption
- HMAC opaque dedup keys
- sensitive Telegram log redaction
- position workflow raw stdout/stderr 全抑制並刪除 temp log
- legacy public LEAPS payload 強制 redacted
- dashboard privacy checks / P0 plaintext detection

### 3.6 Actions 假綠燈

舊 runner 幾乎所有例外都吞掉，process 仍 exit 0。

修正：

- degraded monitoring returns non-zero
- public-safe `workflow_status` + generic `error_codes`
- runner import/startup crash 時 workflow 寫 `runner_process_failed`
- Mission Control 顯示 degraded/failed/stale state

### 3.7 Partial valuation 污染 drawdown

舊 snapshot 對抓不到 price/IV 的部位直接略過，仍回傳一個 partial account total。

修正：

- 任一真實部位無法估值 → `valuation_complete=false`
- `total_estimated_value=null`
- drawdown 不更新
- workflow degraded with `account_value_unavailable`

---

## 4. Mission Control 產品設計

Dashboard 第一屏現在回答：

1. 現在有什麼需要處理？
2. position workflow 是否健康？
3. 哪個 theme / thesis 需要 review？
4. scarce capital 下一步應先看哪個候選？
5. 哪些資料仍是 coverage gap？

主要 public sections：

- summary cards
- Needs attention
- Theme map
- Capital allocation queue
- Portfolio workflow health
- Symbol thesis tracker
- Options / event context

結構化 context：

- HBM / commodity DRAM / NAND 分開
- AI capex shared factor: NVDA / MU / AVGO / MRVL / LITE
- MU / NVDA / SNDK symbol thesis
- manual allocation attention order，不是 automatic buy ranking

---

## 5. Private Telegram risk brief

每次 configured EOD position check 會 silent-send 私有摘要：

- estimated account value
- net / gross delta notional
- delta-equivalent shares
- daily theta
- vega per 1% IV
- symbol concentration
- theme exposure
- explicit `thesis_id` coverage
- option DTE / delta
- market-data gaps

這些詳細資料只存在 process memory 與 Telegram，不寫入 Git、public dashboard、Actions log 或 artifact。

---

## 6. 主要檔案

### Dashboard / thesis

- `src/storage/mission_control_store.py`
- `src/dashboard/build_mission_control.py`
- `src/runners/run_dashboard_build.py`
- `data_store/thesis_tracker.json`
- `data_store/capital_allocation.json`
- `docs/trading_monitor_v2.md`

### Private position / risk

- `src/management/current_positions.py`
- `src/management/leaps_pnl_tracker.py`
- `src/management/portfolio_risk_summary.py`
- `src/management/private_position_privacy.py`
- `src/management/account_drawdown.py`
- `src/runners/run_position_check.py`

### Routing / privacy / workflows

- `src/alerts/deduplication.py`
- `src/alerts/alert_router.py`
- `src/alerts/telegram_bot.py`
- `.github/workflows/position_check.yml`
- `.github/workflows/dashboard_build.yml`
- `.github/workflows/ci.yml`

### Setup / agent contract

- `docs/positions_schema.md`
- `docs/github_secrets_setup.md`
- `AGENTS.md`

---

## 7. 驗證結果

- 新增 PR CI：Python 3.11 + full `python -m pytest -q`
- Last fully inspected green artifact before this handoff commit: CI run #45, head `32ff6c9c3cc510429165c347c56069255a549eb7`
- Result: **359 passed / 1 skipped in 5.17s**
- Tests cover:
  - Mission Control contract/render
  - HBM/DRAM/NAND separation
  - secret priority / malformed fail-closed
  - LEAPS per-contract units
  - redacted public snapshot
  - encrypted account state
  - opaque dedup keys
  - private Telegram log redaction
  - Greeks/concentration brief
  - P1 position routing
  - degraded workflow exit status
  - public LEAPS redaction
  - partial valuation fail-closed

After the handoff/docs/Pages commits, re-check the latest PR head CI and update this section or PR body with the final count before marking ready.

---

## 8. Production activation — owner only

Repository owner must perform these one-time GitHub settings directly. Do not paste values to an agent, issue or PR:

1. Actions secret `POSITIONS_JSON`
2. Actions secret `POSITION_STATE_KEY`
3. Actions variable `ENABLE_GITHUB_PAGES=true`
4. Settings → Pages → Source = GitHub Actions
5. Manually run **Position Management Check**
6. Confirm redacted `position_snapshot.json` says healthy/configured and Telegram receives private brief
7. Manually run **Dashboard Build**
8. Confirm `github-pages` environment exposes the stable URL

If `POSITION_STATE_KEY` is rotated, old encrypted high-water state becomes unreadable and drawdown safely resets to the then-current full valuation.

---

## 9. 已知問題 / yellow flags

1. Current private risk is analytical but not yet an integrated capital-allocation optimizer.
2. `thesis_id` is measured and warned in the brief, but schema validation does not yet require it.
3. Explicit AI-capex / memory correlated-basket exposure is not yet separately calculated; theme aggregation is the current foundation.
4. Hedge coverage ratio and roll-window table can be deeper.
5. Paid options data fields (put skew / OI / unusual activity) remain honest `null` until provider approval.
6. GitHub Pages deployment is gated and cannot be production-tested before owner enables Pages and merges the workflow.
7. Public GitHub scheduled workflows may still be delayed by platform scheduling; stale health is now visible but an external wake-up mechanism remains a separate reliability topic.

---

## 10. 下一步 TODO

### Immediate

- Wait for latest PR-head CI after final docs/workflow commits.
- Update PR #7 body with final architecture, privacy and exact test count.
- Update Issue #6 checklist/status.
- Mark PR #7 ready only when latest CI is green.
- Do not merge without explicit owner instruction.

### P1 continuation

- require or stronger-flag missing `thesis_id`
- explicit correlated-basket exposure for AI capex and memory subthemes
- hedge coverage and contract roll windows
- compare current exposure against allocation queue

### P2+

- dynamic opportunity ranking
- content/event intelligence
- decision-log evaluation, EV and capital-efficiency review

---

## 11. 下次新對話銜接重點

直接讀：

1. `AGENTS.md`
2. 本 handoff
3. `docs/trading_monitor_v2.md`
4. PR #7 latest diff / CI / review threads
5. Issue #6

先確認 PR #7 最新 head 與 CI。若 green，更新 PR/Issue 並請 owner review；不要重做泛泛 repo scan，也不要要求 owner 重講 Trading Monitor 目標。Production activation secrets 必須由 owner 在 GitHub UI 自行設定，agent 永遠不要索取實際值。
