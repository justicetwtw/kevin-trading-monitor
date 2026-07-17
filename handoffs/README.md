# handoffs/ — 跨 session 進度交接

> Handoff 是未完成、跨 session、待 review／rollout 或無法單靠 code 推導的進度快照。它不是第二套真相；與 code／docs／PR 衝突時，以後者為準。

## 新 session 使用方式

1. 先讀 root `AGENTS.md`。
2. 看本目錄檔名日期與本頁 latest 指標。
3. 只讀與當前 task 直接相關的 handoff；已完成且可由 PR/code 推導的歷史不常駐。
4. 不要請 Kevin 重講已寫入 repo 的進度；讀完仍不確定時只問具體問題。

## 現有 handoffs

| 日期 | 檔案 | 主題 |
|---|---|---|
| 2026-05-04 | `2026-05-04-phase-2-5-complete-and-night-debug.md` | Phase 2.5 系列收工與 production debug |
| 2026-05-07 | `2026-05-07-v41-deploy-and-observation.md` | v4.1 deploy 與觀察期 |
| 2026-07-16 | `2026-07-16-trading-monitor-mission-control.md` | Mission Control、私有部位風險、隱私與可靠性 |
| 2026-07-16 | `2026-07-16-trump-market-clock-correction.md` | 台北市場時間、Trump all-post capture、source honesty |
| 2026-07-16 | `2026-07-16-decision-grade-agent-workflow.md` | PR #8 decision engine、quota-aware routing 與 review/activation gates |

> **目前 latest：`2026-07-16-decision-grade-agent-workflow.md`。** PR #8 merge／activation前以該 handoff＋PR current HEAD為接續入口。

## 寫作規則

檔名：`handoffs/YYYY-MM-DD-{kebab-topic}.md`。

建議結構：

```markdown
# {主題} Handoff
> 日期、PR、branch、exact HEAD、狀態

## 執行摘要
## 已完成
## 驗證 evidence
## 已知限制／blocker
## 下一步與 approval gate
## 新 session 銜接
```

- 寫 branch、PR、exact SHA、CI run與實際測試數字；不要只寫「已驗證」。
- 不記 chain-of-thought、secret、完整 private prompt或精確私有持倉。
- 不把投資監測輸出寫成交易指令。
- 完成且 PR body／tests 已足夠時，可刪除或封存暫時 handoff，避免 stale authority。
