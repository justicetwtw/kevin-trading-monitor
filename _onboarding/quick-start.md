# Quick Start — 新 AI session 最短上手路徑

> 目標：任何 AI 在 ~2 分鐘內掌握「這是什麼、現在在哪、規則是什麼」，不必使用者重講。

## 30 秒：這是什麼

- **kevin-trading-monitor** = 選擇權策略**決策輔助**監測系統。
- 全雲端（GitHub Actions 排程）、零月費（yfinance / FRED / RSS / SEC 等免費源）、Telegram 推播。
- **只給訊號，不下單。** 最終買賣決策永遠在人。

## 60 秒：照順序讀這幾份

1. [`../AGENTS.md`](../AGENTS.md) — 進場總則 + 紅線（必讀）。
2. [`AI-ONBOARDING.md`](AI-ONBOARDING.md) — 協作紀律、三層資訊架構。
3. [`../handoffs/`](../handoffs/) 內**日期最新**的一份 — 接續上次進度（挑法見 [`../handoffs/README.md`](../handoffs/README.md)）。

> 截至本檔撰寫，最新 handoff 是 `handoffs/2026-05-07-v41-deploy-and-observation.md`。**請以實際目錄中日期最大的檔為準**，不要把這行寫死當依據。

## 90 秒：要深入時再讀

| 想了解 | 讀 |
|---|---|
| 系統怎麼組起來、一次掃描怎麼流動 | [`architecture.md`](architecture.md) |
| 投資策略現況（含 P0 缺口警示） | [`contexts/strategy.md`](contexts/strategy.md) |
| 資料從哪來、哪些要金鑰 | [`contexts/data-sources.md`](contexts/data-sources.md) |
| 推播怎麼去重 / 排優先級 | [`contexts/alerts.md`](contexts/alerts.md) |
| 排程 workflow 對照 + secrets | [`contexts/github-actions.md`](contexts/github-actions.md) |
| 專案總覽（是什麼、給誰） | [`../context/kevin-trading-project-context.md`](../context/kevin-trading-project-context.md) |

## 紅線速記（細節見 AGENTS.md §4）

- ❌ 不改 trading logic code（`src/signals`、`src/layers`、`src/management`、`src/config/thresholds.py`、`universe.py` …）
- ❌ 不改 workflow 行為（`.github/workflows/*.yml`）
- ❌ 不改 secrets 名稱（`TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` / `FRED_API_KEY` / `SEC_EDGAR_USER_AGENT`）
- ❌ 不改寫 `docs/strategy_v4.md` 的策略語意（該檔已由 Kevin 補入 v5 全文，為策略 single source of truth；AI 不得自行增删推導策略內容）
- ❌ 訊號不得寫成「建議買 / 賣」（決策輔助，非自動下單）
- ❌ 永不 force push；持久化文件一律進 repo

## 環境事實（查證用，非投資建議）

- Python 3.11（CI）；本機曾用 3.14。測試：`pytest`。
- 套件管理：`requirements.txt` + `pyproject.toml`。
- 程式入口：`python -m src.runners.run_*`（由 workflow 觸發）。
- 狀態持久化：`data_store/*.json`（由 `commit-state` 自動 commit，訊息帶 `[skip ci]`）。
