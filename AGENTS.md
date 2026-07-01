# AGENTS.md - Kevin Trading Monitor

## 專案定位

此 repo 是 Kevin 的個人化選擇權策略決策輔助系統。系統以 GitHub Actions 24/7 雲端排程運作，透過 Telegram 推播市場摘要、事件監控、策略訊號與部位管理提醒。系統只做決策輔助與警示，不自動下單；最終交易決策由 Kevin 做出。

此 repo 是 investment / trading monitor 專案，不是金億陽農場自動化 repo。不要把農場 IPM、IoT、compost、cultivation、Dashboard、LINE LIFF、GAS、Google Sheets 或其他農場規則帶進本 repo。

## Codex Environment

建議 Codex environment 名稱：`kevin-trading-monitor`。可接受別名：`invest-monitor`。

非 secret environment variables：

```bash
PROJECT_DOMAIN=invest
PRIMARY_REPO=justicetwtw/kevin-trading-monitor
CONTEXT_ENTRYPOINT=docs/investment_context_v4_2.md
AGENT_MODE=docs_or_pr_only
```

所有 token、API key 與帳號識別值都必須放 GitHub Actions secrets 或平台 secrets。committed 檔案只能記錄 secret 名稱與用途，不得寫入任何實際值，也不要新增 `.env` 作為交付內容。

## 進場必讀

每個 session 在討論模型、修改策略、改 watchlist、調整 workflow 或開 PR 前，先讀：

1. `README.md`
2. `docs/setup_guide.md`
3. `docs/github_secrets_setup.md`
4. `docs/investment_context_v4_2.md`
5. `docs/strategy_v4.md`

若 `docs/strategy_v4.md` 仍是 placeholder 或來源不足，不要自行補完策略規則；先把缺口標明在 PR 或回報中。repo 內容優先於聊天記憶，repo 是 single source of truth。

## 工作邊界

`AGENT_MODE=docs_or_pr_only` 代表 Codex 預設只改 code/docs、跑 test/build、開 PR。不要直接 merge `main`，不要直接 force push，除非 Kevin 明確要求，不要持有或使用 production token。

若 repo 已有 GitHub Actions，deploy、scheduled run、雲端推播與狀態更新由 GitHub Actions 處理。agent 不應把 production secret 搬到本機或 Codex environment，也不應繞過 workflow 直接操作 production。

可以做：

- 修改 Python code、tests、docs、GitHub Actions workflow。
- 在 branch 上 commit、push，開 draft PR 或一般 PR。
- 執行 `python -m pytest -q`、必要的 lint/build 或 workflow YAML 檢查。
- 對 secrets 只提出名稱與設定位置，不接收、不保存、不輸出實際值。

需要停下回報 Kevin：

- 需要真實 token/API key/帳號識別值才能繼續。
- 需要直接 merge `main`、手動跑 production workflow、或調整 repo / Actions 權限。
- 策略文件與程式碼衝突，且會影響實際交易判斷。
- 外部資料來源授權、付費方案、頻率限制或合規風險不明。

## 投資策略與 Watchlist 紀律

修改投資策略、watchlist、threshold、alert routing、部位規則或不可回退決策時，必須在相關文件或 PR 說明標明：

- 日期，格式用 `YYYY-MM-DD`。
- 變更假設與資料來源。
- 主要風險、失效條件與已知限制。
- 是否屬於不可回退決策，若是，說明為什麼不能靜默回退。

不要把 derive 後的推播結果當成策略真相；策略真相放在 repo 文件與設定檔。若 watchlist 或策略由外部對話產生，先整理成 repo diff，再讓實作依 repo 版本進行。

## Secrets 現況

文件目前明列的最低啟動 secrets：

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

目前程式碼或 GitHub Actions workflow 已實際使用的額外 secret / 識別值：

- `FRED_API_KEY`：目前 `src/data/fred_api.py` 與 macro / market brief / signal workflow 會使用。
- `SEC_EDGAR_USER_AGENT`：SEC EDGAR 要求的識別字串，目前 `src/data/sec_edgar.py` 與 SEC / institutional workflow 會使用；這不是 market data API key，但仍不得寫進 committed 檔案。

目前不要預設要求的未使用 market data keys：

- `FINNHUB_API_KEY`
- `POLYGON_API_KEY`
- `ALPHA_VANTAGE_API_KEY`

只有當程式碼、workflow 或文件真的加入使用點時，才新增對應 secret 名稱與設定說明。

## 驗證紀律

本 repo 使用 Python 3.11。一般 code change 先安裝 `requirements.txt`，再跑：

```bash
python -m pytest -q
```

docs-only change 至少檢查 diff 與 Markdown 內容一致性；若未跑測試，要在回報中明講原因。修改 GitHub Actions workflow 時，確認 secret 只透過 `${{ secrets.NAME }}` 注入，且 workflow 仍由 GitHub Actions 排程執行。
