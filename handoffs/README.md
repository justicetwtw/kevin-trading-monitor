# handoffs/ — 跨 session 進度交接

> handoff = 一個 sprint / 一段工作收尾時寫的「給下一個 AI（或下一個你）的交接信」。
> 它是讓**任何 AI 在新對話無縫接續**的關鍵；新 session 開場 SOP 的第 4 步就是讀「最新一份 handoff」。

## 1. 怎麼用（新 session 必做）

1. 看本目錄，挑**檔名日期最大**的 `.md`（檔名格式 `YYYY-MM-DD-{topic}.md`，日期可直接字典序比大小）。
2. 讀它的「執行摘要」「下次新對話銜接 prompt / TODO」段落 → 知道現在卡在哪、下一步是什麼。
3. 需要更早的脈絡再往前翻舊 handoff。
4. **不要請使用者重講進度**；該寫的都在這裡。讀完仍不確定 → 問**具體**問題。

> 注意：handoff 是**當下時點的快照**，可能被後續 sprint 推翻。與程式碼 / `docs/` 衝突時，**以程式碼與規格為準**，並把矛盾回報使用者。handoff 內出現的個人資訊（如本機路徑、chat_id）僅為當時紀錄，**不要複製到其他文件或對外輸出**。

## 2. 現有 handoffs（截至本檔撰寫；以實際目錄為準）

| 日期 | 檔案 | 主題 |
|---|---|---|
| 2026-05-04 | `2026-05-04-phase-2-5-complete-and-night-debug.md` | Phase 2.5 系列收工 + production debug 全紀錄 |
| 2026-05-07 | `2026-05-07-v41-deploy-and-observation.md` | v4.1 五個 sprint 上線 + 觀察期 |

> **目前最新 = `2026-05-07-...`。** 新 session 從它接續。請每次都實際看目錄，不要把這行寫死。

## 3. 怎麼寫一份 handoff（收尾時）

檔名：`handoffs/YYYY-MM-DD-{kebab-topic}.md`（用工作完成當日日期）。

建議結構（沿用既有兩份的風格）：

```markdown
# {專案} — {本次主題} Handoff
> 日期：YYYY-MM-DD
> 里程碑：一句話
> 承接：上一份 handoff 檔名
> 下一篇：預計接續的主題

## 1. 執行摘要        # 3-5 行：這次做了什麼、結果如何
## 2. 改了什麼         # commit / 檔案 / 設計決策（可附 hash）
## 3. 驗證結果         # 測試、實跑、production 觀察
## 4. 已知問題 / yellow flags
## 5. 下次 TODO / 觀察期任務
## 6. 下次新對話銜接重點   # 讓下一個 AI 直接接手的最短說明
```

寫作守則：

- **具體 > 籠統**：寫「Sprint X 已 push origin/main，HEAD=abc1234，待觀察 wall time」，不要寫「做了一些優化」。
- **狀態要可驗證**：上線了沒、在 main 還是 branch、測試幾 pass，都寫清楚。
- **不寫投資建議**：handoff 記的是工程 / 系統狀態，不是買賣指令。
- **不靠記憶**：引用 commit / 檔案 / 數字前先查證。
- 寫完 commit 進 repo（持久化文件一律進 repo，不要只丟暫存沙盒）。
