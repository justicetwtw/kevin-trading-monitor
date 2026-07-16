# Agent Workflow 官方依據與 Repo 判斷邊界

> Last verified: **2026-07-16**
> Scope: OpenAI/Codex、Anthropic/Claude Code、GitHub Actions 的 repository instructions、review trigger、permissions、verification 與 remote delivery。
> 原則：官方文件明確支持的行為列為「官方事實」；本 repo 的 routing、review、cost、merge 與 production gate 另列為 repo judgment。

## 1. OpenAI / Codex 官方事實

官方來源：

- Codex GitHub review: <https://learn.chatgpt.com/docs/third-party/github>
- `AGENTS.md`: <https://learn.chatgpt.com/docs/agent-configuration/agents-md>
- Codex changelog: <https://learn.chatgpt.com/docs/changelog>
- Prompting: <https://learn.chatgpt.com/docs/prompting>
- Permissions: <https://learn.chatgpt.com/docs/permissions>

截至 2026-07-16，官方文件支持：

- PR 頂層 comment 使用精確 `@codex review` 可要求 review；需等待 Codex reaction 與實際 GitHub review，沒有回應不能視為完成。
- Codex GitHub review 聚焦 serious issues，在 GitHub 標示 P0/P1；可在 comment 加一次性 focus。
- Codex 會讀 `AGENTS.md` Review guidelines，並套用 changed file 最近的適用 `AGENTS.md`。
- Automatic reviews 是 Codex settings 的 repository 設定，不是本 repo Actions 自行呼叫 OpenAI inference。
- `AGENTS.md` 應保存廣泛適用的 repo expectations；子目錄可放 nested instructions。模型、alias、reasoning setting 與產品能力必須依當前官方文件和實測重新評估。

## 2. Anthropic / Claude Code 官方事實

官方來源：

- GitHub Actions: <https://code.claude.com/docs/en/github-actions>
- Best practices: <https://code.claude.com/docs/en/best-practices>
- Changelog: <https://code.claude.com/docs/en/changelog>
- Memory / instructions: <https://code.claude.com/docs/en/memory>
- Permissions: <https://code.claude.com/docs/en/permissions>
- Models: <https://platform.claude.com/docs/en/about-claude/models/overview>
- Official action release: <https://github.com/anthropics/claude-code-action/releases/tag/v1>

截至 2026-07-16，官方文件支持：

- GA GitHub action 是 `anthropics/claude-code-action@v1`；舊 `@beta` 的 `mode`、`direct_prompt`、`custom_instructions` 等需遷移為 `prompt` 與 `claude_args`。
- Issue／PR comment 的 `@claude` mention 可觸發 Claude Code GitHub Actions，前提是 GitHub App、workflow、permission 與 `ANTHROPIC_API_KEY` 或替代 provider 已正確配置。
- Claude 會遵守 root `CLAUDE.md`；官方建議保持簡短、廣泛適用，conditional knowledge 放 skills。
- 提供可執行 verification（tests、build、screenshot/fixture）是 coding-agent 工作品質的關鍵；不確定的跨檔工作適合 explore → plan → code。
- Permission 由 GitHub Actions／Claude harness 真正執行；prompt 或 `CLAUDE.md` 不能取代 least-privilege enforcement。
- v1 的 tool allowlist 經 `claude_args --allowedTools` 傳入；官方文件定義為逗號分隔工具清單。
- API key 必須放 GitHub Secrets，Action permissions 只給必要範圍，且人類必須在 merge 前 review Claude 的輸出。

## 3. GitHub Actions 官方事實

官方來源：

- Workflow syntax: <https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax>
- `gh pr checks`: <https://cli.github.com/manual/gh_pr_checks>

截至 2026-07-16：

- Scheduled workflow 支援 IANA `timezone`，因此可直接以 `Asia/Taipei` 表達維護性排程；市場交易排程仍應以 canonical market-clock code 與 DST/holiday semantics 驗證。
- `gh pr checks` 可區分 pass/fail/pending/skipping/cancel；`--required` 只列 branch/ruleset 標為 required 的 checks。
- Public repo 的 comment-trigger workflow 必須自行 gate actor、精確 command 與 permissions，不能因為 workflow 存在就信任任意留言者。
- `issue_comment` workflow 使用 default branch 上的 workflow 定義。新增 comment-trigger workflow 的同一支 bootstrap PR 無法依賴尚未進入 default branch 的新檔案來審查自己；必須使用既有 GitHub App／外部 review path，或在明確回報此 bootstrap limitation 後由 Kevin 決定如何啟用。

## 4. 2026-07-16 Repo judgments（不是官方要求）

1. **Stable root model-neutral**：`AGENTS.md` 固定角色、安全、投資品質、approval 與 evidence，不固定模型排行。
2. **Thin Claude wrapper**：`CLAUDE.md` 只引用 canonical rules 與 Claude-specific reminders。
3. **One task / one implementation PR / one owner**：PR body、diff、tests、review 與 remote HEAD 是 durable truth。
4. **Exact-SHA handoff**：所有 implementation/review handoff 綁定 PR number＋40-character current remote HEAD；過期即 `BLOCKED`。
5. **Dual independent review for high risk**：策略、資金風險、隱私、workflow、source ingestion 或跨層變更原則上要求 Codex＋Claude；低風險 docs 可由 Kevin 決定降級。
6. **Kevin gate**：review pass 只移到 `needs-kevin`；merge、Ready、deploy、production、secret 與 acceptable-risk 決策都需 Kevin 對該次 PR 明確授權。
7. **Deterministic CI first**：tests、fixtures、schema checks、live probe 與 privacy checks blocking；模型 review 不能替代 CI。
8. **No false decision-grade**：資料不足時降級 readiness，不用模型文字或中性分數補洞。
9. **Capability watcher only alerts**：官方 source drift／到期只建立或更新 `needs-kevin` issue；不自動接受 baseline、改 routing、安裝 plugin/MCP、merge 或 deploy。
10. **30-day reverification**：即使 fingerprint 未變，活躍使用期間至少每 30 天人工查核官方 docs、workspace availability、permissions 與實際 delivery path。
11. **Pin third-party action**：workflow 以官方 v1 release 目前指向的完整 SHA `e90deca47693f9457b72f2b53c17d7c445a87342` 執行，並由 capability watcher 提醒重新查核；這是供應鏈風險控制，不代表自動接受後續 tag 漂移。
12. **Review-only Claude tools**：Claude review 只允許 `Read,Glob,Grep`，不允許執行 branch 內程式；deterministic tests 由無模型 secret 的 CI workflow 執行。

## 5. Reverify triggers

- OpenAI／Anthropic 修改 GitHub review/action、trigger、model alias、prompting、instructions、skills/hooks/subagents、permissions、context 或 changelog。
- Repo 發現 instruction 未載入、mention 無回應、remote HEAD 未前進、review loop、prompt injection、Actions 假綠燈或 context 退化。
- `ANTHROPIC_API_KEY`、Codex cloud、GitHub App、branch protection、workspace entitlement 或主要 tool surface 改變。
- Claude v1 release tag 不再指向已核准的 pinned SHA，或官方 action security guidance 改變。
- 距離 `last_verified` 滿 30 天。
