# Trading Monitor v2 — Thesis-first Mission Control

Date: 2026-07-16  
Status: P0 foundation  
Epic: #6

## Why v1 felt useless

The existing system runs many scheduled jobs, but the dashboard is mostly a passive state dump. It does not lead with the questions that matter:

1. What needs attention now?
2. Which position or thesis changed?
3. Which opportunity deserves scarce capital next?
4. Which instrument lens is appropriate: stock, deep-ITM LEAPS, defined-risk options, leveraged ETF, or wait?
5. What would invalidate the thesis?

The old dashboard also contained many explicit Phase 1 placeholders. That was honest, but a screen dominated by `null` fields still had little practical value.

## Product definition

Trading Monitor v2 is a **Personal Capital Allocation / Thesis Monitor**.

- Telegram: urgent P0/P1 exceptions and scheduled briefs.
- Dashboard: complete review state, including non-urgent context.
- TradingView: charting and visual technical analysis.
- GitHub repo: source of truth for strategy, theses, configuration and review history.
- No automated orders.

## First-screen contract

The first screen must be useful within 30 seconds:

- market regime
- needs-attention queue
- position workflow health
- tracked themes and subthemes
- capital-allocation attention order
- symbol theses, catalysts, invalidation and review dates
- supporting options/event context

Normal states are secondary. Exceptions appear first.

## Theme-first rules

### Memory is not one bucket

The monitor must preserve three separate subthemes:

- HBM
- commodity DRAM
- NAND

A datapoint about one category must not automatically change the thesis for the others. MU has mixed exposure; SNDK/WDC are more direct NAND beta.

### AI-capex correlation

NVDA, MU, AVGO, MRVL and LITE can share a market-level AI-capex factor. Symbol-level monitoring must therefore include correlated basket risk rather than assuming every move is company-specific.

### Options-market fear

Price weakness alone is insufficient. The desired state includes:

- whether implied volatility is being bought
- put-skew change
- OI concentration / key strikes
- unusual activity
- whether support and selling pressure confirm the move

Fields that require paid data remain explicit `null` until a provider is approved and connected. No synthetic placeholder score is allowed.

## P0 implementation

### Mission Control payload

`src/storage/mission_control_store.py` joins:

- regime state
- existing watchlist scores
- IVR/IVP state
- thesis tracker
- capital-allocation queue
- redacted position-workflow health

### Mission Control UI

`src/dashboard/build_mission_control.py` replaces the old dashboard entrypoint while preserving legacy JSON payloads under `public/dashboard/data/`.

The new page leads with:

1. summary cards
2. needs-attention queue
3. theme map
4. capital-allocation queue
5. portfolio workflow status
6. thesis tracker
7. supporting options and event context

### Position-monitor bug fix

The previous runner read `snapshot["total_value"]`, but `get_account_snapshot()` returns `total_estimated_value`. Drawdown tracking therefore never received the account total. P0 fixes the field mismatch.

### Public-repo privacy boundary

This repository is public. Exact holdings, strikes, costs and account value must not be committed.

`run_position_check` now commits only a redacted health snapshot containing:

- configured / empty status
- aggregate position count
- long/short option counts
- timestamp
- privacy marker

The real in-memory account snapshot is still used for drawdown logic during the workflow run, but exact details are not persisted to Git.

## Structured repo context

`data_store/thesis_tracker.json` consolidates the June–July 2026 discussion into reviewable theme and symbol objects.

`data_store/capital_allocation.json` stores a manual attention order. It is not an automatic ranking and never creates an order. Live dashboard fields are joined when available; missing coverage remains visible.

## Remaining work

### P1 — secure private position input

The public repo cannot hold real positions. A secure runtime input is required before cloud LEAPS, short-delta, hedge and drawdown checks can be trusted. The implementation must:

- keep the secret out of Git and generated dashboard files
- validate schema before use
- fail closed on malformed input
- expose only redacted workflow health publicly
- document rotation and update steps

### P1 — thesis-linked portfolio risk

- map each private position to `thesis_id`
- compute delta-equivalent exposure and concentration
- track theta, vega, DTE and roll windows
- compare correlated AI-capex exposure across symbols
- route only material exceptions to Telegram

### P2 — opportunity ranking

Rank themes and candidates using:

- thesis strength and catalyst timing
- price/expectation gap
- options fear/flow
- capital efficiency
- downside and invalidation distance
- correlation with current exposure
- instrument fit

The result remains decision support, not a trade command.

### P3 — content intelligence

Generalize podcast, newsletter, RSS and KOL collection into deduplicated event objects with source, confidence, importance, affected themes and half-life.

### P4 — evaluation

Add decision review, expected value, drawdown, capital efficiency and baseline comparisons.
