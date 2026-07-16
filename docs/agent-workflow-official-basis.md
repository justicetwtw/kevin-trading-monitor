# Agent Workflow 官方依據與 Repo 判斷邊界

> Last verified: **2026-07-16**
> Scope: OpenAI/Codex、Anthropic/Claude Code、GitHub Actions 的 repository instructions、review、subagents／teams、permissions、verification 與 remote delivery。
> 原則：官方文件明確支持的行為列為「官方事實」；本 repo 的 routing、cost、review、merge 與 production gate另列為 dated repo judgment。

## 1. OpenAI／Codex 官方事實

官方來源：

- Codex GitHub review: <https://learn.chatgpt.com/docs/third-party/github>
- `AGENTS.md`: <https://learn.chatgpt.com/docs/agent-configuration/agents-md>
- Subagents: <https://learn.chatgpt.com/docs/agent-configuration/subagents>
- Codex changelog: <https://learn.chatgpt.com/docs/changelog>
- Prompting: <https://learn.chatgpt.com/docs/prompting>
- Permissions: <https://learn.chatgpt.com/docs/permissions>
- ChatGPT release notes: <https://help.openai.com/en/articles/6825453-chatgpt-release-notes>
- GPT-5.6 in ChatGPT: <https://help.openai.com/en/articles/20001354-gpt-56-in-chatgpt>

截至 2026-07-16，官方文件支持：

- PR頂層comment使用精確`@codex review`可要求review；需等待Codex reaction與實際GitHub review，沒有回應不能視為完成。
- Codex review讀PR diff與repository guidance，聚焦serious issues，GitHub review只標示P0/P1；可在comment加一次性focus。
- Codex會讀changed file最近的適用`AGENTS.md`；root instructions應保存廣泛適用expectations，conditional knowledge可放nested instructions／skills。
- Automatic reviews是Codex settings的repository設定，不是本repo Actions自行呼叫OpenAI inference。
- Subagent可把exploration、tests、triage、log/source analysis等noisy／read-heavy工作移出主context，獨立工作可平行節省時間。
- Subagent workflow每個agent都會做自己的model/tool work，因此比相同single-agent run消耗更多tokens；平行write-heavy工作容易造成衝突與協調成本。
- ChatGPT Work的Ultra使用最大reasoning，並可主動delegate適合的獨立工作；其他intelligence level可由prompt明確要求delegation。
- Model、reasoning、availability、price與quota是快速變動產品事實，應由dated record＋實測重新評估，不可寫成永久hierarchy。

## 2. Anthropic／Claude Code 官方事實

官方來源：

- Subagents: <https://code.claude.com/docs/en/sub-agents>
- Agent teams: <https://code.claude.com/docs/en/agent-teams>
- GitHub Actions: <https://code.claude.com/docs/en/github-actions>
- Best practices: <https://code.claude.com/docs/en/best-practices>
- Changelog: <https://code.claude.com/docs/en/changelog>
- Memory / instructions: <https://code.claude.com/docs/en/memory>
- Permissions: <https://code.claude.com/docs/en/permissions>
- Models: <https://platform.claude.com/docs/en/about-claude/models/overview>

截至 2026-07-16，官方文件支持：

- Claude subagent可在定義或單次invocation指定model，也可`inherit`主session；可用較低成本model做bounded exploration，但實際availability仍受組織allowlist與產品版本影響。
- Subagents有獨立context，適合隔離專業工作；lead必須提供足夠task context並整合結果。
- Agent teams使用多個獨立session，協調overhead與token usage顯著高於single session；最適合可獨立平行的research／review／new-feature work，不適合sequential、same-file或依賴密集工作。
- Claude Code GitHub Actions可用GitHub App＋`ANTHROPIC_API_KEY`／Bedrock／Google Cloud provider觸發`@claude`工作，並要求secrets、permissions與human review正確配置。
- Permission由Claude Code／GitHub Actions harness真正執行；prompt或`CLAUDE.md`不能取代least-privilege enforcement。
- `CLAUDE.md`應簡短、具體且廣泛適用；conditional knowledge放skills或scoped instructions。

## 3. GitHub Actions 官方事實

官方來源：

- Workflow syntax: <https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax>
- `gh pr checks`: <https://cli.github.com/manual/gh_pr_checks>

截至 2026-07-16：

- Scheduled workflow支援IANA`timezone`；市場交易排程仍應以canonical market-clock code與DST/holiday semantics驗證。
- `gh pr checks`可區分pass/fail/pending/skipping/cancel；`--required`只列branch/ruleset標為required的checks。
- Public repo的comment-trigger workflow必須自行gate actor、精確command與permissions，不能因workflow存在就信任任意留言者。
- `issue_comment` workflow使用default branch上的workflow定義；bootstrap PR不能假設同一PR新增的comment-trigger workflow已可自我驗證。

## 4. 2026-07-16 Repo judgments（不是官方要求）

1. **Stable root model-neutral**：`AGENTS.md`固定角色、安全、投資品質、approval與evidence，不固定provider/model排行。
2. **Dated runtime assignment**：owner根據當下quota／availability、task fit、authenticated delivery path、tools與failure mode選擇；當期產品名稱只放dated record／routing report。
3. **One task／one PR／one owner**：branch write ownership不因subagent或reviewer分叉。
4. **Optional bounded subagents**：只在獨立、可驗證且預期節省成本／latency／context時使用；`subagents_used=false`是有效結果。
5. **SHA-bound routing report**：`agent-routing-report:v1`與金億陽canonical schema對齊，記錄owner、delegation、實際可得的usage evidence、lead re-verification、tests與CI；不要求chain-of-thought或fabricated metrics。
6. **No AI inference Actions**：本repo不新增OpenAI／Anthropic API key、AI cron或普通comment/push inference Action；Claude/Fable透過已驗證authenticated task surface派工，無path時回報`BLOCKED_DELIVERY`。
7. **Verified Codex adapter**：`@codex review`保留；是否交付以reaction＋GitHub review為準。
8. **Non-owner review**：independent reviewer不得是implementation owner；可行時跨provider/model family，findings回原owner，最多兩輪。
9. **Kevin gate**：review pass只移至`needs-kevin`；merge、Ready、deploy、production、secret與acceptable-risk決策都需Kevin對該次PR明確授權。
10. **Deterministic CI first**：tests、fixtures、schema checks、live probe、privacy與routing-report verifier blocking；模型review不能替代CI。
11. **Trusted default-branch verifier**：ChatOps不得執行PR branch提供的verifier，避免implementation owner自我授權；bootstrap PR使用CI＋人工／connector替代gate。
12. **No false decision-grade**：資料不足時降級readiness，不用模型文字或中性分數補洞。
13. **Capability watcher only alerts**：官方source drift／到期只建立或更新`needs-kevin` issue；不自動接受baseline、改routing、安裝plugin/MCP、merge或deploy。
14. **30-day maximum reverification**：即使fingerprint未變，活躍使用期間至少每30天人工查核；fast-changing products可用更頻繁watcher，但同fingerprint不得重複騷擾。

## 5. Reverify triggers

- OpenAI／Anthropic修改model availability、GitHub review/action、subagents／agent teams、reasoning／effort、prompting、instructions、skills/hooks、permissions、context、quota或changelog。
- Repo發現instruction未載入、mention無回應、remote HEAD未前進、review loop、prompt injection、Actions假綠燈或context退化。
- Codex cloud、Fable／Claude authenticated task surface、GitHub App、branch protection、workspace entitlement或主要tool surface改變。
- 可取得的usage／credits／latency evidence與目前runtime assignment假設衝突。
- 距離`last_verified`滿30天。
