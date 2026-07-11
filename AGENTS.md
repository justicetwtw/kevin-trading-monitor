# AGENTS.md — AI Agent 進場指南（LLM 中立）

> 這份檔案是**任何 AI agent**（Claude / ChatGPT / Codex / 其他）進入本 repo 的第一份必讀。
> 它與工具無關。不論你是哪一個模型、哪一個介面，規則都一樣。

## 0. 一句話定位

`kevin-trading-monitor` 是一套**選擇權策略「決策輔助」監測系統**：GitHub Actions 在雲端排程跑、抓資料、評分、把訊號用 Telegram 推播給使用者。

**它不是自動下單系統。** 系統只產出訊號與摘要，最終買賣決策永遠在人。任何 AI 都不得把系統訊號改寫成「你應該買 / 賣」這類直接投資指令（見 §4 紅線）。

此 repo 是 investment / trading monitor 專案，**不是金億陽農場自動化 repo**。不要把農場 IPM、IoT、compost、cultivation、Dashboard、LINE LIFF、GAS、Google Sheets 或其他農場規則帶進本 repo。

## 1. 唯一真實來源：這個 GitHub repo

跨對話、跨模型、跨時間，**GitHub repo（最新 main branch）是唯一真實來源**。

- 對話 context 會沉、會滿、會被總結；模型會換版本。任何要保留超過一個 session 的東西，都必須寫進 repo。
- 若你的記憶 / 訓練資料 / 過去對話與 repo 內容衝突，**一律以 repo 最新內容為準**。
- 沒有依據時直接說「repo 裡查不到」，**不要臆測、不要用「我記得」當依據**。

## 2. 新 session 開場 SOP（照順序讀，30 秒上手）

1. 讀本檔 `AGENTS.md`（你正在這）。
2. 讀 `_onboarding/AI-ONBOARDING.md`（協作紀律 + 三層資訊架構）。
3. 讀 `_onboarding/quick-start.md`（最短上手路徑）。
4. 讀 `handoffs/` 內**日期最新**的一份（接續上次進度）— 怎麼挑見 `handoffs/README.md`。
5. 需要深入某子系統時，再讀對應的 `_onboarding/contexts/{topic}.md`。
6. 要深入系統設定與策略全貌時，再讀 `docs/setup_guide.md`、`docs/github_secrets_setup.md`、`docs/investment_context_v4_2.md`、`docs/strategy_v4.md`（placeholder，見 §4 紅線 4）。

讀完還不確定狀態 → 問**具體**問題（「Sprint X 上線了沒？」），不要泛問「最近做了什麼」，也不要叫使用者重講一遍。

## 3. 大型程式碼不常駐，需要時才讀

`src/` 約 80+ 檔、上萬行。**不要把整個 codebase 載進 context**。

- 先靠 `_onboarding/contexts/*` 與 `_onboarding/architecture.md` 建立地圖。
- 要改 / 要查特定模組時，再用搜尋工具定位該檔再讀。
- 寫規格時模糊的命名（常數 / 函數 / 路徑）標註「待確認」，動手前先搜尋既有 code 確認真實命名，**既有命名與風格 > 你的範例**。

## 4. 紅線（HARD — 不可跨越）

1. **不改任何 trading logic code**：`src/signals/`、`src/layers/`、`src/management/`、`src/data/`、`src/config/thresholds.py`、`universe.py` 等策略 / 風險邏輯，未經使用者明確指示不得更動。
2. **不改 workflow 行為**：`.github/workflows/*.yml` 的排程、觸發、步驟不得擅改。
3. **不改 secrets 名稱**：既有 secret（完整清單見 §10 Secrets 現況）名稱固定，不得重命名；新增 secret 需使用者確認，並同步更新 §10 與 `docs/github_secrets_setup.md`。
4. **不補寫不存在的投資策略**：`docs/strategy_v4.md` 目前是 placeholder（P0 缺口）。策略全文尚未補入，**AI 不得自行推導、不得補寫**。詳見 `_onboarding/contexts/strategy.md`。
5. **嚴禁把系統訊號寫成直接投資建議**：本 repo 是決策輔助，不是自動下單。描述訊號時用「系統評為 X 分 / 觸發 Y 條件」，不要寫「建議買進 / 該賣出」。
6. **永不 force push**；持久化文件一律進 repo，不要只丟暫存沙盒。
7. **不主動觸發對使用者收費或有額度上限的外部服務**（含付費 API、額度受限的推播）。

## 5. 動手前自我檢查

- 這資訊要保留超過一個 session 嗎？→ 要 → 寫進 repo（`handoffs/` 或 `_onboarding/`）。
- 我是憑印象還是查證？→ 一律查證（搜尋 repo / 既有 code）。
- 我假設的命名 / 路徑 / 風格是真的嗎？→ 不確定就標「待確認」。
- 我要改的東西踩到 §4 任何一條紅線嗎？→ 踩到就停，先問使用者。
- 我有沒有把系統訊號講成投資指令？→ 有就改回中性描述。

## 6. 檔案地圖（onboarding 層）

| 路徑 | 作用 |
|---|---|
| `AGENTS.md` | 本檔，任何 AI 的進場總則（LLM 中立） |
| `CLAUDE.md` | Claude Code 專用薄殼，內容指回本檔 |
| `_onboarding/AI-ONBOARDING.md` | 協作紀律、三層資訊架構、跨 LLM 接手法 |
| `_onboarding/quick-start.md` | 最短上手路徑 |
| `_onboarding/architecture.md` | 系統架構地圖（onboarding 視角） |
| `_onboarding/contexts/strategy.md` | 策略現況 + P0 placeholder 警示 |
| `_onboarding/contexts/data-sources.md` | 資料來源與所需金鑰 |
| `_onboarding/contexts/alerts.md` | 推播 pipeline 與去重 / 優先級 |
| `_onboarding/contexts/github-actions.md` | 排程 workflow 與 secrets 對照 |
| `handoffs/README.md` | handoff 慣例與最新進度入口 |
| `context/kevin-trading-project-context.md` | 專案總覽（是什麼、給誰、現況） |

> onboarding 內容若與程式碼衝突，**以程式碼與 `docs/` 既有規格為準**，並把矛盾回報給使用者，不要自行「修正」程式。

## 7. Codex Environment

建議 Codex environment 名稱：`kevin-trading-monitor`。可接受別名：`invest-monitor`。

非 secret environment variables：

```bash
PROJECT_DOMAIN=invest
PRIMARY_REPO=justicetwtw/kevin-trading-monitor
CONTEXT_ENTRYPOINT=docs/investment_context_v4_2.md
AGENT_MODE=docs_or_pr_only
```

所有 token、API key 與帳號識別值都必須放 GitHub Actions secrets 或平台 secrets。committed 檔案只能記錄 secret 名稱與用途，不得寫入任何實際值，也不要新增 `.env` 作為交付內容。

## 8. 工作邊界

`AGENT_MODE=docs_or_pr_only` 代表 agent 預設只改 code/docs、跑 test/build、開 PR。不要直接 merge `main`，不要直接 force push，除非使用者明確要求，不要持有或使用 production token。

deploy、scheduled run、雲端推播與狀態更新由 GitHub Actions 處理。agent 不應把 production secret 搬到本機或 agent environment，也不應繞過 workflow 直接操作 production。

可以做：

- 修改 Python code、tests、docs、GitHub Actions workflow（依 §4 紅線 1-2：需使用者指示）。
- 在 branch 上 commit、push，開 draft PR 或一般 PR。
- 執行 `python -m pytest -q`、必要的 lint/build 或 workflow YAML 檢查。
- 對 secrets 只提出名稱與設定位置，不接收、不保存、不輸出實際值。

需要停下回報使用者：

- 需要真實 token/API key/帳號識別值才能繼續。
- 需要直接 merge `main`、手動跑 production workflow、或調整 repo / Actions 權限。
- 策略文件與程式碼衝突，且會影響實際交易判斷。
- 外部資料來源授權、付費方案、頻率限制或合規風險不明。

## 9. 投資策略與 Watchlist 紀律

修改投資策略、watchlist、threshold、alert routing、部位規則或不可回退決策時，必須在相關文件或 PR 說明標明：

- 日期，格式用 `YYYY-MM-DD`。
- 變更假設與資料來源。
- 主要風險、失效條件與已知限制。
- 是否屬於不可回退決策，若是，說明為什麼不能靜默回退。

不要把 derive 後的推播結果當成策略真相；策略真相放在 repo 文件與設定檔。若 watchlist 或策略由外部對話產生，先整理成 repo diff，再讓實作依 repo 版本進行。

## 10. Secrets 現況

文件目前明列的最低啟動 secrets：

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

目前程式碼或 GitHub Actions workflow 已實際使用的額外 secret / 識別值：

- `FRED_API_KEY`：目前 `src/data/fred_api.py` 與 macro / market brief / signal workflow 會使用。
- `SEC_EDGAR_USER_AGENT`：SEC EDGAR 要求的識別字串，目前 `src/data/sec_edgar.py` 與 SEC / institutional workflow 會使用；這不是 market data API key，但仍不得寫進 committed 檔案。
- `GMAIL_SENDER` / `GMAIL_APP_PASSWORD` / `EMAIL_RECIPIENT`：`active_etf_digest.yml` 與 `gooaye_digest.yml` 的 email 寄送。
- `GEMINI_API_KEY` / `GEMINI_MODEL`：`gooaye_digest.yml` 的摘要生成。

目前不要預設要求的未使用 market data keys：

- `FINNHUB_API_KEY`
- `POLYGON_API_KEY`
- `ALPHA_VANTAGE_API_KEY`

只有當程式碼、workflow 或文件真的加入使用點時，才新增對應 secret 名稱與設定說明。

## 11. 驗證紀律

本 repo 使用 Python 3.11。一般 code change 先安裝 `requirements.txt`，再跑：

```bash
python -m pytest -q
```

docs-only change 至少檢查 diff 與 Markdown 內容一致性；若未跑測試，要在回報中明講原因。修改 GitHub Actions workflow 時，確認 secret 只透過 `${{ secrets.NAME }}` 注入，且 workflow 仍由 GitHub Actions 排程執行。
