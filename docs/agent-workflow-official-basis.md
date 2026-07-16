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

截至 2026-07-16，官方文件支持：

- PR 頂層 comment 使用精確 `@codex review` 可要求 review；需等待 Codex reaction 與實際 GitHub review，沒有回應不能視為完成。
- Codex review 讀 PR diff 與 repository guidance，聚焦 serious issues，GitHub review 只標示 P0/P1；可在 comment 加一次性 focus。
- Codex 會讀 changed file 最近的適用 `AGENTS.md`；root instructions 應保存廣泛適用 expectations，conditional knowledge 可放 nested instructions／skills。
- Automatic reviews 是 Codex settings 的 repository 設定，不是本 repo Actions 自行呼叫 OpenAI inference。
- Subagent 可把 exploration、tests、triage、log/source analysis 等 noisy／read-heavy 工作移出主 context，獨立工作可平行節省時間。
- Subagent workflow 每個 agent 都會做自己的 model/tool work，因此比相同的 single-agent run 消耗更多 tokens；平行 write-heavy 工作容易造成衝突與協調成本。
- ChatGPT Work 的 Ultra 使用最大 reasoning，並可主動 delegate 適合的獨立工作；其他 intelligence level 可由 prompt 明確要求 delegation。
- Model、reasoning、availability、price 與 quota 是快速變動產品事實，應由 dated record＋實測重新評估，不可寫成永久 hierarchy。

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

- Claude subagent 可在定義或單次 invocation 指定 model，也可 `inherit` 主 session；可用較低成本 model做 bounded exploration，但實際 availability 仍受組織 allowlist 與產品版本影響。
- Subagents 有獨立 context，適合隔離專業工作；lead 必須提供足夠 task context並整合結果。
- Agent teams 使用多個獨立 session，協調 overhead 與 token usage 顯著高於 single session；最適合可獨立平行的 research／review／new-feature work，不適合 sequential、same-file 或依賴密集工作。
- Claude Code GitHub Actions 可用 GitHub App＋`ANTHROPIC_API_KEY`／Bedrock／Google Cloud provider觸發 `@claude` 工作，並要求 secrets、permissions 與 human review 正確配置。
- Permission 由 Claude Code／GitHub Actions harness 真正執行；prompt 或 `CLAUDE.md` 不能取代 least-privilege enforcement。
- `CLAUDE.md` 應簡短、具體且廣泛適用；conditional knowledge 放 skills或 scoped instructions。

## 3. GitHub Actions 官方事實

官方來源：

- Workflow syntax: <https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax>
- `gh pr checks`: <https://cli.github.com/manual/gh_pr_checks>

截至 2026-07-16：

- Scheduled workflow 支援 IANA `timezone`；市場交易排程仍應以 canonical market-clock code 與 DST/holiday semantics 驗證。
- `gh pr checks` 可區分 pass/fail/pending/skipping/cancel；`--required` 只列 branch/ruleset 標為 required 的 checks。
- Public repo 的 comment-trigger workflow 必須自行 gate actor、精確 command 與 permissions，不能因 workflow 存在就信任任意留言者。
- `issue_comment` workflow 使用 default branch 上的 workflow 定義；bootstrap PR 不能假設同一 PR 新增的 comment-trigger workflow已可自我驗證。

## 4. 2026-07-16 Repo judgments（不是官方要求）

1. **Stable root model-neutral**：`AGENTS.md` 固定角色、安全、投資品質、approval 與 evidence，不固定 provider/model 排行。
2. **Dated runtime assignment**：owner 根據當下 quota／availability、task fit、authenticated delivery path、tools 與 failure mode選擇；當期產品名稱只放 dated record／routing report。
3. **One task／one PR／one owner**：branch write ownership不因 subagent 或 reviewer 分叉。
4. **Optional bounded subagents**：只在獨立、可驗證且預期節省成本／latency／context時使用；`subagents_used=false` 是有效結果。
5. **SHA-bound routing report**：`agent-routing-report:v1` 記錄 owner assignment、delegation、實際可得的 usage evidence、lead re-verification、tests與 CI；不要求 chain-of-thought或 fabricated metrics。
6. **No AI inference Actions**：本 repo 不新增 OpenAI／Anthropic API key、AI cron或普通 comment/push inference Action；Claude/Fable透過已驗證 authenticated task surface派工，無 path 時回報 `BLOCKED_DELIVERY`。
7. **Verified Codex adapter**：`@codex review` 保留；是否交付以 reaction＋GitHub review為準。
8. **Non-owner review**：independent reviewer不得是 implementation owner；可行時跨 provider/model family，findings回原 owner，最多兩輪。
9. **Kevin gate**：review pass只移至 `needs-kevin`；merge、Ready、deploy、production、secret與 acceptable-risk決策都需 Kevin 對該次 PR明確授權。
10. **Deterministic CI first**：tests、fixtures、schema checks、live probe、privacy與 routing-report verifier blocking；模型 review不能替代 CI。
11. **No false decision-grade**：資料不足時降級 readiness，不用模型文字或中性分數補洞。
12. **Capability watcher only alerts**：官方 source drift／到期只建立或更新 `needs-kevin` issue；不自動接受 baseline、改 routing、安裝 plugin/MCP、merge或 deploy。
13. **30-day maximum reverification**：即使 fingerprint未變，活躍使用期間至少每 30 天人工查核；fast-changing products可用更頻繁 watcher，但同 fingerprint不得重複騷擾。

## 5. Reverify triggers

- OpenAI／Anthropic修改 model availability、GitHub review/action、subagents／agent teams、reasoning／effort、prompting、instructions、skills/hooks、permissions、context、quota或 changelog。
- Repo發現 instruction未載入、mention無回應、remote HEAD未前進、review loop、prompt injection、Actions假綠燈或 context退化。
- Codex cloud、Fable／Claude authenticated task surface、GitHub App、branch protection、workspace entitlement或主要 tool surface改變。
- 可取得的 usage／credits／latency evidence與目前 runtime assignment假設衝突。
- 距離 `last_verified`滿 30 天。
