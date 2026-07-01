# Codex Environment - Kevin Trading Monitor

最後確認日期：2026-07-01

## Environment

建議名稱：`kevin-trading-monitor`

可接受別名：`invest-monitor`

目標 repo：`justicetwtw/kevin-trading-monitor`

此 environment 專用於 investment / trading monitor，不共用金億陽農場 automation repo 的 AGENTS、onboarding、GAS、Sheet、Dashboard 或 IoT 規則。

## Non-secret Env Vars

在 Codex environment 設定下列非 secret env vars：

```bash
PROJECT_DOMAIN=invest
PRIMARY_REPO=justicetwtw/kevin-trading-monitor
CONTEXT_ENTRYPOINT=docs/investment_context_v4_2.md
AGENT_MODE=docs_or_pr_only
```

不要把 token、API key、chat id、EDGAR identity 或任何實際秘密值寫進 repo。實際值只放 GitHub Actions secrets 或平台 secrets。

## Codex Setup Script

建議 Codex setup script：

```bash
set -euo pipefail
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip check
```

此 script 只建立 Python 3.11 執行環境與依賴，不放任何 secret，也不直接觸發 production workflow。

## Default Validation

一般 code change：

```bash
python -m pytest -q
```

Docs-only change：檢查 diff 與文件連結是否合理；若沒有跑 pytest，在 PR 或回報中標明是 docs-only。

## GitHub Actions 現況

截至 2026-07-01，repo 已有 `.github/workflows/`，主要由 `schedule` 和 `workflow_dispatch` 觸發；未掃到 `push` / `pull_request` 觸發的通用 CI workflow。

已存在的 workflow：

```text
aaii_update.yml
brief_sanity.yml
earnings_update.yml
health_check.yml
institutional_scan.yml
iv_history_update.yml
liquidity_check.yml
macro_layer.yml
market_brief.yml
news_monitor.yml
position_check.yml
sec_monitor.yml
signal_scan_eod.yml
signal_scan_intraday.yml
trump_monitor.yml
tsmc_revenue.yml
twstock_signal.yml
```

Scheduled run、Telegram 推播與狀態 commit 由 GitHub Actions 執行。Codex agent 預設只開 PR，不直接 merge `main`，也不直接持有 production token。

## Secrets 現況

文件最低啟動需求：

| Secret name | 用途 |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot 推播 |
| `TELEGRAM_CHAT_ID` | Telegram 接收對象，程式支援逗號分隔多個 chat id |

目前程式碼 / workflow 已實際使用：

| Secret name | 用途 | 目前使用點 |
| --- | --- | --- |
| `FRED_API_KEY` | FRED 宏觀資料 | `src/data/fred_api.py`、`macro_layer.yml`、`market_brief.yml`、`signal_scan_eod.yml`、`signal_scan_intraday.yml` |
| `SEC_EDGAR_USER_AGENT` | SEC EDGAR identity，避免未識別請求 | `src/data/sec_edgar.py`、`sec_monitor.yml`、`institutional_scan.yml` |

目前不要預設要求：

| Secret name | 狀態 |
| --- | --- |
| `FINNHUB_API_KEY` | 目前未掃到程式碼或 workflow 使用點 |
| `POLYGON_API_KEY` | 目前未掃到程式碼或 workflow 使用點 |
| `ALPHA_VANTAGE_API_KEY` | 目前未掃到程式碼或 workflow 使用點 |

新增任何 market data API key 前，先用 `rg` 確認實際使用點，並同步更新 AGENTS / setup 文件 / workflow env。
