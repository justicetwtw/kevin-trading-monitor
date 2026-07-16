# Trading Monitor v3 — Decision-grade Mission Control

Date: 2026-07-16  
Status: implemented in Draft PR #8; not merged or production-activated  
Prior foundation: [`trading_monitor_v2.md`](trading_monitor_v2.md)

## Product change

v2 solved the passive-dashboard, privacy and false-green workflow problems. v3 adds a stricter product contract:

> The system may rank research attention, but it must not call a setup decision-ready until current price/as-of/source, valid scenarios, Kevin-approved assumptions, fresh evidence, a future proof point, screen coverage and correlated-risk context are all present.

This is a decision-support system, not an automated trading system.

## What is now implemented

### 1. Decision readiness rather than a second decorative score

- Company thesis, security readiness and decision posture are separate fields.
- States: `not_decision_grade`, `screen_grade`, `review_ready`, `re_underwrite`.
- Missing data is never replaced by a neutral value.
- Existing watchlist score remains a secondary heuristic screen and retains coverage/component status.
- Scenario EV/skew is calculated only after validating source, as-of, current price, positive cases and probabilities summing to 100%.
- Scenario price anchor drift over 5% or date mismatch over 3 days invalidates decision grade.
- Mathematically valid but unapproved assumptions, partial market context, stale evidence, an expired proof point or unapproved thresholds can reach only `screen_grade`.

### 2. Public delayed market context

A scheduled workflow refreshes each allocation candidate after the U.S. close:

- current close/as-of;
- 1M, 3M and 6M return;
- distance from 52-week high;
- 20-day realized volatility.

The source is labeled delayed/unofficial yfinance data. It is timing/risk context only, not an official tape, valuation or target price. Unavailable candidates produce a committed safe degraded state followed by a red workflow.

### 3. Scenario and evidence gaps are visible

Mission Control now exposes:

- readiness counts and blocking inputs;
- market-context health;
- scenario expected return and downside/upside skew when valid;
- manual research priority separately from dynamic readiness;
- research-candidate correlation baskets;
- decision-log sample size and Brier score only when resolved probability forecasts exist.

The initial MU/NVDA/SNDK/LITE scenario fields remain `null`; the system therefore correctly reports them as not decision-grade rather than inventing price targets or probabilities.

### 4. Private thesis-linked portfolio risk

Private Telegram adds:

- overlapping basket gross Delta;
- protective negative Delta / positive Delta;
- roll windows at ≤90, ≤180 and ≤270 days;
- missing and invalid `thesis_id` counts;
- unmapped correlation risk and review flags.

Public state contains aggregate counts/ratios only. It cannot contain symbols, basket names, shares, contracts, strikes, expiries, costs, account value or detailed Greeks.

`portfolio_hedge` is an explicit risk-control thesis. Recognition of a QQQ/SPY/SMH/SOXL put does not prove effectiveness; basis risk, carry, liquidity, expiry mismatch and intended-alpha preservation remain human review items.

### 5. Durable dual-agent governance

The workflow adapted from `jin-yi-yang-bot` adds:

- one implementation owner per branch;
- exact 40-character remote-HEAD handoffs;
- blocking deterministic CI and workflow-contract verification;
- trusted-actor ChatOps;
- official `@codex review` adapter;
- trusted exact-SHA Claude review using `anthropics/claude-code-action@v1`;
- OpenAI/Anthropic official-capability watcher;
- permanent Kevin-specific merge gate.

A reviewer pass never authorizes merge. Every implementation PR must be reported with exact tested SHA, CI evidence, review verdicts and residual limitations; Kevin must explicitly authorize that PR.

## What v3 still does not prove

v3 improves epistemic discipline and risk visibility. It does **not** prove investment alpha.

Still required for empirically validated capital allocation:

1. Source-backed issuer/sector KPI time series and consensus/variant expectations.
2. Current valuation and price-implied expectations for each security.
3. Paid or otherwise reliable historical options skew/OI/UOA data.
4. Walk-forward/out-of-sample testing with realistic baselines.
5. Transaction costs, bid/ask spread, liquidity, taxes and executable instrument constraints.
6. A real append-only decision writer/resolver and enough resolved forecasts for calibration.
7. Performance attribution separating thesis alpha, factor beta, timing, convexity and hedging cost.
8. Exchange holiday/special early-close calendar integration.

Until those exist, the correct output is often `wait_for_proof`, not a confident buy/sell label.
