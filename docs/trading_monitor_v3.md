# Trading Monitor v3 — Decision-grade readiness and auditable agent workflow

> Date: 2026-07-16  
> Status: Draft PR implementation; not merged or activated  
> Product boundary: decision support only, no automated orders.

## 1. Product outcome

Trading Monitor v3 adds a fail-closed decision layer on top of Mission Control:

- company thesis status, security readiness and decision posture are separate;
- scenario math requires current price, as-of, source and probabilities that sum to 100%;
- stale/misaligned market anchors, unapproved thresholds, weak evidence and expired catalysts cannot become `review_ready`;
- correlated research baskets and private portfolio basket/hedge/roll risk are explicit;
- decision history is append-only and calibration remains insufficient until enough resolved forecasts exist.

The implementation improves decision hygiene; it does not prove alpha and does not invent missing valuation inputs.

## 2. Agent workflow outcome

The repo uses the same model-neutral, quota-aware workflow as the current `jin-yi-yang-bot` contract:

- Kevin works with the strongest available Conversation／Workflow Orchestrator;
- owner is chosen per task using quota／availability, task fit, authenticated delivery path, tools and failure mode;
- one PR has one branch owner;
- optional lower-cost subagents handle only bounded, independent, verifiable support work;
- implementation completion requires a current-HEAD `agent-routing-report:v1`, deterministic CI and remote delivery;
- independent reviewer must not be the implementation owner; use a different provider/model family when practical;
- findings return to the original owner, with at most two repair rounds;
- Kevin alone authorizes merge, Ready, deployment and production risk.

Repo Actions do not hold OpenAI／Anthropic API keys or run model inference. Codex review uses the verified repository integration. Fable／Claude／other workers use an authenticated task surface; missing delivery path is `BLOCKED_DELIVERY`, not an invented mention.

## 3. Decision readiness

### `not_decision_grade`

Core price/source/as-of/scenario or thesis requirements are absent, market context is unhealthy, or scenario anchor conflicts materially with the current market snapshot.

### `screen_grade`

Math exists but evidence, approval, catalyst, score coverage or freshness remains incomplete. This supports research prioritization only.

### `review_ready`

All required inputs, approvals, evidence, source posture, dated catalyst, screen coverage, correlation baskets and instrument lenses are present. This means “ready for Kevin review,” never “buy.”

### `re_underwrite`

Company thesis is broken/invalidated or materially impaired. Security ranking is suspended until the thesis is rebuilt.

## 4. Market context

`Decision Market Context` refreshes delayed public timing/risk fields after U.S. close:

- current close/as-of;
- 1M/3M/6M return;
- distance from 52-week high;
- 20-day annualized realized volatility.

This source is delayed/unofficial and cannot substitute for official tape, consensus estimates, paid options history or valuation underwriting. Partial/unavailable data remains visible and fails closed.

## 5. Private portfolio decision risk

Exact positions remain only in process memory and private Telegram. The private brief adds:

- overlapping theme/subtheme basket Delta exposure;
- protective negative Delta（僅 long put／short stock；short call 只計入 Delta offset，不是下檔保護）/ positive Delta，另列總 Delta offset ratio;
- ≤90/180/270-day roll windows;
- missing/invalid thesis IDs and unmapped basket coverage;
- review flags with threshold origin.

Public state contains only aggregate counts/ratios and generic flags; never symbols, basket names, strikes, expiries, costs or account value.

## 6. Routing evidence

Before `/agent-fix-complete <current-head>`, a trusted PR comment must contain a schema-valid `agent-routing-report:v1` with:

- exact 40-character current remote HEAD;
- dated owner/provider/surface/session mode and assignment basis;
- whether subagents were used and why;
- bounded delegation ownership/outcome/evidence when applicable;
- actual usage/credit/latency evidence or explicit `unavailable` source;
- lead re-verification;
- tests and passing CI;
- non-owner reviewer assignment.

The deterministic verifier rejects Bot/untrusted reports, stale SHA, incomplete schema, invented unavailable metrics, and sensitive/reasoning keys. ChatOps also queries actual GitHub checks; the report cannot certify itself.

## 7. Activation after merge

Owner-only actions, not performed by this Draft PR:

1. Configure `POSITIONS_JSON` and `POSITION_STATE_KEY` without sharing values in chat/PR/issues.
2. Configure `ENABLE_GITHUB_PAGES=true` and Pages source = GitHub Actions if the public-safe dashboard should deploy.
3. Run **Decision Market Context**, **Position Management Check** and **Dashboard Build** once.
4. Ensure every production position has an approved `thesis_id`, including `portfolio_hedge` for hedge instruments.
5. Confirm public state remains redacted and all workflows are healthy.
6. Confirm the selected reviewer has an authenticated task/review surface; do not add a model API secret to Actions merely for review.

## 8. Known limitations

- No approved company valuation scenarios are supplied by this implementation; initial candidates remain not decision-grade.
- yfinance is delayed/unofficial.
- Paid put-skew/OI/UOA history remains unconnected.
- Walk-forward/out-of-sample baselines, transaction costs, option spread/liquidity, tax and sufficiently large decision history remain necessary before claiming empirical value.
- Exchange holidays and special early closes remain a separate market-calendar limitation.
