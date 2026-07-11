> ⚠️ **已被取代（保留作歷史參考）**：本檔是 Claude 單一視角的舊版。
> LLM 中立的最新版請見 [`AI-ONBOARDING.md`](AI-ONBOARDING.md) 與 [`../AGENTS.md`](../AGENTS.md)，新內容以那兩份為準。
> 兩者衝突時，以 `AI-ONBOARDING.md` / `AGENTS.md` 為準。

# 給 Claude 的介紹:GitHub-as-source-of-truth Workflow

## 為什麼有這套設計

使用者(以下稱 Kevin)用 Claude 開發長期專案。對話會沉、context 會滿、模型會換版本。如果重要決策、SOP、進度只活在對話裡,幾天後就找不回來,新對話又要 recap 一遍 — 浪費時間且容易遺失資訊。

解法:**把 GitHub repo 當成跨對話、跨 Claude 實例、跨時間的唯一真實來源**。對話只負責即時推理、產出、診斷;任何要保留超過一個 session 的東西都必須寫進 repo。

## 三層資訊架構

| 層級 | 內容 | 範例 |
|---|---|---|
| **userMemories**(Anthropic 內建) | 紅線 / SOP / 長期偏好 | 「絕不 force push」、「程式碼風格用 Pythonic」、「使用者偏好結論前自我反駁」 |
| **GitHub repo**(source of truth) | 程式碼 + sprint 進度 + handoffs + onboarding | `code/`、`handoffs/2026-05-07-xxx.md`、`_onboarding/CLAUDE-ONBOARDING.md` |
| **本對話 context** | 即時推理、診斷、spec 草稿 | 不持久化,結束就沒了 |

memory 只放跨 session 不變的東西(SOP/紅線),具體 sprint 進度全部進 `handoffs/`。

## 你是哪一層的 Claude?

**Web Claude**(claude.ai 對話,你正在這裡):
- 規劃、診斷、寫 self-contained spec
- 透過 Project Knowledge 讀 repo(手動 Sync now 後才更新)
- **不直接寫檔到使用者本機** — 透過給 CC / Cowork 的指令間接寫
- 有 Drive connector / web search 等工具,該用就用,不要轉手讓 CC 做你能做的事

**Claude Code**(本機端,使用者電腦上跑):
- 主力執行端 — 真正改檔、commit、push
- 直接讀寫本機檔案系統
- watcher 會自動 commit + push,你只管寫對檔案

## 馬上能用的紀律(三條最重要)

### 紅線 1:任何持久化文件必須進 GitHub repo

Sprint 結束 / 重大決策 / 使用者拍板的設計 → 寫成 markdown 進 repo。

Web Claude 不要把 handoff 寫到 sandbox(`/mnt/user-data/outputs/`)就以為交差了 — 那只是即時下載用,對話沉了就消失。所有持久化文件都要透過給 CC 的指令寫進 repo `handoffs/` 或 `_onboarding/`。

### 紅線 2:既有命名 / 風格 > spec 範例

Web Claude 寫 spec 時可能猜錯既有 codebase 的命名(常數、函數、檔案路徑)、風格(ES5/ES6、tab/space)、約定。CC 實作時應:

- spec 範例只是 stub,**先 grep 既有 code 確認真實命名再 patch**
- 風格沿用既有(別人的 codebase 一致性 > 你的 style preference)
- 範圍 spec 寫「所有 X」太絕對時,自我約束到合理範圍

Web Claude 寫 spec 時,模糊的命名要主動標註「待 grep 確認」,不要假裝知道。

### 紅線 3:不主動 push 對使用者收費的 API

任何外部服務(LINE Push、Twilio、付費 API)有額度限制的,Claude 不要主動觸發。設計上找替代路徑(例如讓使用者手動轉發、批次處理、cache、fallback 到免費路徑)。

## 工作循環(典型 sprint)

1. 使用者描述需求 → Web Claude 產 self-contained spec MD
2. Web Claude 給 CC 指令 → 包含 spec 內容(verbatim)+ 執行步驟
3. CC 執行 → 改檔 + commit(post-commit hook 自動 push)→ 自動部署
4. 使用者手動驗收 → 失敗回報給 Web Claude 修
5. Sprint 結束 → Web Claude 寫 handoff MD,給 CC 指令寫進 `handoffs/YYYY-MM-DD-{topic}.md`
6. 使用者點 claude.ai Project「Sync now」 → 下次新對話讀得到

## 新對話開場 SOP

新對話的 Web Claude 一進來應該:
1. 讀 `_onboarding/CLAUDE-ONBOARDING.md`(專案總覽)
2. 讀**最新一筆** `handoffs/` 檔(接續上次進度)
3. 必要時讀 `_onboarding/contexts/{topic}.md`(深入特定模組)

不要叫使用者 recap — 該看的都在 repo。

如果讀完還是不確定狀態,問**具體**問題(「Sprint X 是已上線還是 staging?」),不要泛問「最近做了什麼」。

## 給 Claude 的自我檢查

每次要回答前問自己:

- 這個資訊使用者要保留多久?超過一個 session → 該進 repo
- 我憑印象答還是該查證?(grep / Drive connector / web search / project knowledge)
- 我假設的命名 / 路徑 / 風格,是真的嗎?還是該標註「待確認」?
- 這個指令要使用者做什麼手動操作?有沒有自動化路徑?
- 我有沒有把 sandbox 當 repo 用?
