# AGENTS.md — AI Agent 進場指南（LLM 中立）

> 這份檔案是**任何 AI agent**（Claude / ChatGPT / Codex / 其他）進入本 repo 的第一份必讀。
> 它與工具無關。不論你是哪一個模型、哪一個介面，規則都一樣。

## 0. 一句話定位

`kevin-trading-monitor` 是一套**選擇權策略「決策輔助」監測系統**：GitHub Actions 在雲端排程跑、抓資料、評分、把訊號用 Telegram 推播給使用者。

**它不是自動下單系統。** 系統只產出訊號與摘要，最終買賣決策永遠在人。任何 AI 都不得把系統訊號改寫成「你應該買 / 賣」這類直接投資指令（見 §4 紅線）。

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

讀完還不確定狀態 → 問**具體**問題（「Sprint X 上線了沒？」），不要泛問「最近做了什麼」，也不要叫使用者重講一遍。

## 3. 大型程式碼不常駐，需要時才讀

`src/` 約 80+ 檔、上萬行。**不要把整個 codebase 載進 context**。

- 先靠 `_onboarding/contexts/*` 與 `_onboarding/architecture.md` 建立地圖。
- 要改 / 要查特定模組時，再用搜尋工具定位該檔再讀。
- 寫規格時模糊的命名（常數 / 函數 / 路徑）標註「待確認」，動手前先搜尋既有 code 確認真實命名，**既有命名與風格 > 你的範例**。

## 4. 紅線（HARD — 不可跨越）

1. **不改任何 trading logic code**：`src/signals/`、`src/layers/`、`src/management/`、`src/data/`、`src/config/thresholds.py`、`universe.py` 等策略 / 風險邏輯，未經使用者明確指示不得更動。
2. **不改 workflow 行為**：`.github/workflows/*.yml` 的排程、觸發、步驟不得擅改。
3. **不改 secrets 名稱**：`TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`、`FRED_API_KEY`、`SEC_EDGAR_USER_AGENT` 名稱固定，不得重命名或新增。
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
| `_onboarding/contexts/github-actions.md` | 17 個排程 workflow 與 secrets 對照 |
| `handoffs/README.md` | handoff 慣例與最新進度入口 |
| `context/kevin-trading-project-context.md` | 專案總覽（是什麼、給誰、現況） |

> onboarding 內容若與程式碼衝突，**以程式碼與 `docs/` 既有規格為準**，並把矛盾回報給使用者，不要自行「修正」程式。
