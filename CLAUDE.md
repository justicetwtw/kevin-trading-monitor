# CLAUDE.md

@AGENTS.md

本檔刻意保持薄。所有模型共用的正式規則、投資決策品質、隱私、routing report、review 與 merge gate 均以 root `AGENTS.md` 為準；跨 agent durable workflow 見 `docs/agent-team-workflow.md`。

Claude Code 專屬提醒：

- 先確認 current remote PR HEAD 與 task contract 綁定的 40-character SHA 相同，並確認本 session 有 authenticated delivery path；不成立就回報 `BLOCKED`／`BLOCKED_DELIVERY`，不得假裝已接手。
- Fable／Claude implementation owner 可用 bounded subagents，但 branch write ownership不得分叉；lead 必須重新驗證並在 `agent-routing-report:v1`如實記錄。
- Independent review 只做 fresh-context、diff-first 審查，不接管 implementation branch；輸出 `PASS`、`CHANGES_REQUIRED` 或 `BLOCKED`。
- 每個 material finding 必須附 file/line 或 diff hunk、failure scenario、可重現證據與建議修法；不要製造 style-only blocker。
- 不要把普通 `@claude` mention、Bot回覆或 task-start當成 delivery evidence；以 authenticated task、remote HEAD與 deterministic evidence為準。
- `data_store/*.json` 可能由 scheduled workflow 以 `[skip ci]` 更新；不要把 state commit 當成產品 code ownership。
- Python 3.11；一般驗證為 `python -m pytest -q`、`python scripts/verify_agent_workflow_contract.py`。
- 未經 Kevin 對該 PR 明確授權，不得 merge、Ready、deploy、手動 production workflow、操作 secret 或新增外部 permission。
