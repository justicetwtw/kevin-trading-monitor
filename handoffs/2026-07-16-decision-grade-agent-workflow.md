# Decision-grade Mission Control + quota-aware agent workflow Handoff

> 日期：2026-07-16  
> Repo：`justicetwtw/kevin-trading-monitor`  
> PR：#8（Draft）  
> Branch：`agent/decision-grade-mission-control`  
> Exact HEAD：以 PR current remote HEAD 為準；本檔不可硬寫會過期的 SHA  
> Merge／production：未授權、未執行

## 1. 執行摘要

PR #8 同時處理兩層：

1. Decision Engine v1：把 Mission Control 從描述性 dashboard 改成 fail-closed 的 company thesis／security readiness／decision posture 系統。
2. Agent governance：套用 `jin-yi-yang-bot` 最新 quota-aware、model-neutral、single-owner、SHA-bound workflow。

## 2. Workflow 已落地內容

- Root `AGENTS.md`：動態 owner assignment、optional bounded subagents、non-owner review、Kevin merge gate。
- `docs/agent-team-workflow.md`：canonical roles、authenticated delivery adapters、兩輪停止條件。
- `docs/agent-runtime-preferences-2026-07.md`：Kevin 當期 Ultra／strongest-orchestrator preference，明確標為 dated、可重新評估。
- `agent-routing-report:v1`：放在 trusted PR comment，綁 current 40-character HEAD；避免把 HEAD commit 回 branch 造成自我變更循環。
- `scripts/verify_agent_routing_report.py`：驗 owner、subagent delegation、usage evidence、lead re-verification、tests、CI、trusted actor 與 forbidden sensitive/reasoning keys。
- `/agent-fix-complete`／`/agent-review-pass`：驗 exact HEAD、routing report與 GitHub actual checks。
- Capability watcher：追蹤 OpenAI Codex review／AGENTS／subagents與 Anthropic subagents／agent teams／permissions／context。
- Repo 移除 Claude inference GitHub Action；不需要 `ANTHROPIC_API_KEY`／`OPENAI_API_KEY` 作 agent workflow secret。

## 3. Delivery contract

- Codex review：已驗證 adapter為 PR comment `@codex review`；需看到 reaction＋GitHub review。
- Fable／Claude／其他 worker：使用 authenticated task surface，傳 PR number＋current HEAD＋角色＋durable contract。
- 沒有 authenticated surface時回報 `BLOCKED_DELIVERY`；不得 invent `@claude`／`@fable`。
- 一支 branch同時只有一個 implementation owner；reviewer不得接管 branch。

## 4. Decision Engine 已落地內容

- `not_decision_grade`／`screen_grade`／`review_ready`／`re_underwrite`。
- Scenario機率、source、as-of、price anchor、evidence freshness、catalyst與 approval fail-closed。
- Delayed public market timing context。
- AI-capex／memory／HBM／DRAM／NAND／compute／optical correlation baskets。
- 私有 thesis-ID、basket Delta、hedge coverage、roll-window Telegram risk；公開 state只留 aggregate ratios/counts。
- Append-only decision log與 Brier calibration；少量樣本不得宣稱有效。

## 5. Merge 前 acceptance gate

1. Current HEAD 的 full `python -m pytest -q`。
2. `python scripts/verify_agent_workflow_contract.py`。
3. Agent Capability Watch offline audit。
4. Blocking Trump live source probe。
5. Trusted current-HEAD `agent-routing-report:v1`。
6. `/agent-fix-complete <exact-head>` 成功。
7. Non-owner fresh-context review；findings回原 owner，最多兩輪。
8. `/agent-review-pass <exact-head>` 只移至 `needs-kevin`。
9. 向 Kevin 回報 exact tested HEAD、CI、review verdict、限制與 activation步驟。
10. Kevin 對 PR #8 明確授權後才可 merge。

## 6. Post-merge owner-only activation

- 設定 `POSITIONS_JSON`、`POSITION_STATE_KEY`。
- 若要 Pages：`ENABLE_GITHUB_PAGES=true`＋Pages source GitHub Actions。
- 手動跑 Decision Market Context、Position Management Check、Dashboard Build。
- 私有部位每筆使用 approved `thesis_id`；hedge可用 `portfolio_hedge`。
- 驗證 public state無 ticker／basket／strike／cost／account value。

## 7. 已知限制

- 初始候選沒有 Kevin核准、source-backed valuation scenario，因此仍應 `not_decision_grade`。
- yfinance延遲且非 official tape。
- Paid skew/OI/UOA未接入。
- Walk-forward/out-of-sample、交易成本、options spread/liquidity、tax與足夠 decision history仍缺。
- Exchange holiday／special early close另案處理。
- Routing-report usage metrics若產品不提供，必須記 `unavailable`，不得估算。
