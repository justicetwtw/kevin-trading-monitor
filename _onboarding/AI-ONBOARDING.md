# AI-ONBOARDING — 跨 LLM 的 GitHub-as-source-of-truth 協作法

> LLM 中立版。對 Claude / ChatGPT / Codex / 其他 agent 一視同仁。
> 先讀過 [`../AGENTS.md`](../AGENTS.md) 再看本檔（本檔是它的展開）。

## 1. 為什麼要這套設計

使用者用多個 AI（不同模型、不同介面、不同時間）開發同一個長期專案。對話會沉、context 會滿、模型會換版本。如果重要決策、SOP、進度只活在某一段對話裡，幾天後就找不回來，換一個 AI 又要從頭 recap — 浪費時間又容易遺失資訊。

解法：**把 GitHub repo 當成跨對話、跨 AI、跨時間的唯一真實來源**。對話只負責即時推理、產出、診斷；任何要保留超過一個 session 的東西都必須寫回 repo。

## 2. 三層資訊架構

| 層級 | 內容 | 壽命 | 範例 |
|---|---|---|---|
| **AI 端記憶 / 偏好**（各家內建，非本 repo） | 跨 session 不變的紅線 / 風格偏好 | 長期但與工具綁定 | 「永不 force push」「沿用既有命名」 |
| **GitHub repo（source of truth）** | 程式碼 + 規格 + onboarding + handoffs | 永久、可審計 | `src/`、`docs/`、`handoffs/2026-05-07-*.md`、`_onboarding/` |
| **本對話 context** | 即時推理、診斷、規格草稿 | 結束即消失 | 尚未寫進 repo 的暫定設計 |

重點：**只有中間那層是大家共用的真相**。AI 端記憶綁特定工具，換一個 AI 就讀不到；對話 context 一沉就沒。所以「要留」的東西一律往中間那層寫。

## 3. 不同 AI 角色（能力不同，紀律相同）

不同介面能做的事不一樣，但對 repo 的紀律一致：

- **能直接讀寫檔案 / 跑 git 的 agent**（如 Claude Code、Codex CLI、本環境）：直接改檔、commit、開 PR。改動前先搜尋既有 code 對齊命名與風格。
- **只能對話、不能直接寫本機的 AI**（如純聊天介面）：產出 self-contained 規格 / handoff 文字，交給能寫檔的 agent 寫進 repo。**不要把產出只丟在對話或暫存沙盒就當交差** — 對話一沉就消失。

不論哪一種，最終「留下來的東西」都必須進 repo。

## 4. 紅線（與 `AGENTS.md` §4 同步，這裡補充情境）

1. **持久化文件必進 repo**：sprint 收尾、重大決策、使用者拍板的設計 → 寫成 markdown 進 `handoffs/` 或 `_onboarding/`。
2. **既有命名 / 風格 > 規格範例**：規格裡的命名可能是猜的；實作前先搜尋既有 code 確認真實命名。風格沿用既有（一致性 > 個人偏好）。規格範圍寫「所有 X」太絕對時，自我收斂到合理範圍。
3. **不主動觸發收費 / 受限的外部服務**：付費 API、額度受限的推播，設計時找替代路徑（手動轉發、快取、fallback 免費路徑）。
4. **不改 trading logic / workflow 行為 / secrets 名稱**（見 `AGENTS.md`）。
5. **不擅改策略全文**：`docs/strategy_v4.md` 已由 Kevin 補入完整 v5 全文，是策略 single source of truth（AGENTS.md §4）；AI 不得自行增删或推導策略語意，衝突時以 PR 釐清（見 `contexts/strategy.md`）。
6. **訊號 ≠ 投資建議**：本系統是決策輔助。描述系統輸出時保持中性（「評為 72 分 / 觸發否決」），不要寫成「建議買進」。

## 5. 典型工作循環

1. 使用者描述需求 → AI 產出 self-contained 規格（含真實命名，模糊處標「待確認」）。
2. 能寫檔的 agent 實作 → 改檔 + commit（feature branch，不直接動 main）。
3. CI / GitHub Actions 跑；使用者手動驗收。
4. 失敗 → 回報 → 修。
5. Sprint 收尾 → 寫 handoff 進 `handoffs/YYYY-MM-DD-{topic}.md`（格式見 `handoffs/README.md`）。
6. 下一個新 session（任何 AI）→ 讀 onboarding + 最新 handoff，無縫接續。

## 6. 新對話開場 SOP（再強調）

1. `AGENTS.md` → 2. 本檔 → 3. `quick-start.md` → 4. **最新一份** `handoffs/` → 5. 視需要 `contexts/{topic}.md`。

不要叫使用者 recap；該看的都在 repo。讀完仍不確定 → 問**具體**問題。

## 7. 每次回答前自我檢查

- 這資訊要保留多久？超過一個 session → 進 repo。
- 我憑印象還是查證？→ 一律查證（搜尋 repo / 既有 code / 既有規格）。
- 我假設的命名 / 路徑 / 風格是真的嗎？→ 不確定標「待確認」。
- 我有沒有踩紅線（改邏輯 / 改 workflow / 改 secrets / 補寫策略 / 訊號講成建議）？
- 我有沒有把暫存沙盒當 repo 用？

## 8. 與既有文件的關係

- 本檔取代舊的 `_onboarding/CLAUDE-ONBOARDING.md`（Claude 單一視角）。舊檔保留作歷史參考，新內容以本檔為準。
- 系統「事實」（架構、資料源、推播、排程）的細節在 `_onboarding/contexts/*` 與 `docs/*`。本檔只談**協作紀律**。
- 任何 onboarding 內容若與程式碼 / `docs/` 規格衝突 → 以程式碼與規格為準，並把矛盾回報使用者。
