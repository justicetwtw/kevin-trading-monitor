# Project Context — kevin-trading-monitor

> 專案總覽：給任何 AI 一頁掌握「這是什麼、給誰、現在在哪」。
> 事實以 repo 最新 main 為準；本檔若與程式碼 / `docs/` 衝突，以後者為準並回報矛盾。

## 1. 是什麼

一套**個人化選擇權策略「決策輔助」監測系統**。GitHub Actions 在雲端 24/7 排程，抓市場 / 宏觀 / 事件 / 基本面資料，評分後把訊號與每日 brief 用 **Telegram** 推播。

設計哲學（README）：

1. **完全免費**：GitHub public repo + Actions + yfinance / FRED / RSS / SEC = $0/月。
2. **零維護**：設置完成後幾乎不需動手。
3. **佛系操作**：5–15 分鐘延遲符合長線策略。
4. **最終決策權在使用者**：系統給訊號，人下單。

> **定位紅線**：這是決策輔助，**不是自動下單**。系統不產生、AI 也不得改寫出「建議買 / 賣」這類直接投資指令。

## 2. 給誰用

- 主要使用者（repo 擁有者）與其家人共用（多 chat_id 推播）。
- 跨多個 AI（Claude / ChatGPT / Codex）協作開發，因此採 GitHub-as-source-of-truth + onboarding + handoffs 架構（見 `AGENTS.md`、`_onboarding/`）。

## 3. 系統涵蓋範圍（功能面）

- **三大核心訊號**：Sell CALL / Sell PUT(Wheel) / LEAPS 進場。
- **Layer 0 宏觀層**（7 子模組）：macro regime / breadth / distribution / bubble / put-call / VIX 結構 / AAII。
- **Layer 0+ 事件層**：Trump Truth Social / RSS 新聞 / SEC 8-K。
- **Layer F 基本面層**：基本面 / 分析師 / 13F / Form 4 內部人 等。
- **部位管理**（5 模組）：LEAPS 損益 / Short Delta / 對沖 DTE / 帳戶回撤 / 部位載入。
- **台股模組**：00631L + 2330 三級加碼 + 主動 ETF 跟單。
- **每日 Brief**：6 種排程（us_eod / tw_open / tw_close / us_premarket / us_open / us_midday）。

技術細節分層見 `_onboarding/architecture.md` 與 `_onboarding/contexts/*`。

## 4. 技術事實（查證用）

| 項目 | 值 |
|---|---|
| 語言 / 執行 | Python（CI 用 3.11）；純後端、無前端 |
| 程式入口 | `python -m src.runners.run_*`（GitHub Actions 觸發）|
| 排程 | 20 個 workflow（`.github/workflows/`，見 `contexts/github-actions.md`）|
| 推播 | Telegram HTTP API（`src/alerts/telegram_bot.py`，多 chat_id）|
| 狀態 | `data_store/*.json`（`commit-state` 自動 commit，訊息帶 `[skip ci]`）|
| 套件 | `requirements.txt` + `pyproject.toml` |
| 測試 | `pytest`（`tests/`）|
| Secrets | `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` / `FRED_API_KEY` / `SEC_EDGAR_USER_AGENT` |
| 規模 | `src/` 約 80+ 檔、上萬行（依 handoffs）|

> **版本別混**：`settings.py: VERSION="0.1.0"` 是程式包版本；「v4 / v4.1」是策略 / sprint 版本。

## 5. 現況與已知缺口（截至最新 handoff 2026-05-07，請以 repo 為準）

- v4.1 五個 sprint 已上線 origin/main，處於「觀察期」累積真實使用數據。
- **P0 缺口**：`docs/strategy_v4.md` 仍是 **placeholder**，策略全文尚未補入 → AI 不得自行推導（見 `_onboarding/contexts/strategy.md`）。
- IVR 需 ≥30 天累積才有意義（`iv_history.json` 由 `run_iv_history_update` 每日累積中）。
- `positions.json` 預設 `mode_2`，多為 `_example`；真實部位由使用者自行填（schema 見 `docs/positions_schema.md`，且該檔不入 git）。
- Cloudflare Worker 備援觸發（Sprint 2.5.10）**未實作**（卡 GitHub PAT），不要當它已存在。
- 已知小債：`requirements.txt` 仍列 `python-telegram-bot`（傳輸層已改 httpx）；部分 README / `PHASE_2_STRATEGY_AND_DATA.md` 數字（如「13 workflow」）已過時，**以實際檔案為準**。

## 6. 文件導覽

| 想知道 | 看 |
|---|---|
| 任何 AI 的進場規則 + 紅線 | `AGENTS.md` |
| 協作紀律 / 跨 LLM 接手 | `_onboarding/AI-ONBOARDING.md` |
| 最短上手 | `_onboarding/quick-start.md` |
| 架構地圖 | `_onboarding/architecture.md` |
| 策略現況（含缺口） | `_onboarding/contexts/strategy.md` |
| 資料源 / 金鑰 | `_onboarding/contexts/data-sources.md` |
| 推播機制 | `_onboarding/contexts/alerts.md` |
| 排程 / secrets | `_onboarding/contexts/github-actions.md` |
| 最新進度 | `handoffs/`（最新一份）+ `handoffs/README.md` |
| 既有規格 | `docs/`（`architecture.md` / `STRATEGY_PHILOSOPHY.md` / `setup_guide.md` / `positions_schema.md` …）|
