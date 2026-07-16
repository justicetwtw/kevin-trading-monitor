# Trading Monitor v2 — Thesis-first Mission Control

Date: 2026-07-16  
Status: P0 Mission Control + P1 private portfolio risk foundation  
Epic: #6

## Why v1 felt useless

The old system ran many scheduled jobs, but the user-facing result was mostly a passive state dump. It did not lead with the questions that matter:

1. What needs attention now?
2. Which position or thesis changed?
3. Which opportunity deserves scarce capital next?
4. Which instrument lens is appropriate: stock, deep-ITM LEAPS, defined-risk options, leveraged ETF, or wait?
5. What would invalidate the thesis?

Many dashboard fields were also explicit Phase 1 placeholders. Honest `null` values are preferable to fabricated data, but a screen dominated by placeholders still has little practical value.

## Product definition

Trading Monitor v2 is a **Personal Capital Allocation / Thesis Monitor**.

- Telegram: urgent P0/P1 exceptions and private scheduled briefs.
- Dashboard: complete public review state and non-urgent context.
- TradingView: charting and visual technical analysis.
- GitHub repo: source of truth for strategy, theses, configuration and review history.
- No automated orders.

## First-screen contract

The first screen must be useful within 30 seconds:

- market regime
- needs-attention queue
- private position-workflow health
- tracked themes and subthemes
- capital-allocation attention order
- symbol theses, catalysts, invalidation and review dates
- supporting options/event context

Normal states are secondary. Exceptions appear first.

## Theme-first rules

### Memory is not one bucket

The monitor preserves separate subthemes for:

- HBM
- commodity DRAM
- NAND

A datapoint about one category must not automatically change the thesis for the others. MU has mixed exposure; SNDK/WDC are more direct NAND beta.

### AI-capex correlation

NVDA, MU, AVGO, MRVL and LITE can share a market-level AI-capex factor. Symbol-level monitoring must include correlated basket risk rather than assuming every move is company-specific.

### Options-market fear

Price weakness alone is insufficient. The desired state includes:

- whether implied volatility is being bought
- put-skew change
- OI concentration / key strikes
- unusual activity
- whether support and selling pressure confirm the move

Fields that require paid data remain explicit `null` until a provider is approved and connected. No synthetic placeholder score is allowed.

## Implemented foundation

### Mission Control payload and UI

`src/storage/mission_control_store.py` joins regime state, existing watchlist scores, IVR/IVP state, thesis tracking, capital-allocation context and redacted position-workflow health.

`src/dashboard/build_mission_control.py` replaces the dashboard entrypoint while preserving existing JSON contracts. The page leads with:

1. summary cards
2. needs-attention queue
3. theme map
4. capital-allocation queue
5. portfolio workflow health
6. thesis tracker
7. compact options/event context

### Structured thesis context

- `data_store/thesis_tracker.json` consolidates the June–July 2026 memory and AI-capex discussion into reviewable theme and symbol objects.
- `data_store/capital_allocation.json` stores a manual attention order. It is not an automatic buy ranking and never creates an order.

### Secure private position input

The scheduled position workflow reads real holdings only from the encrypted GitHub Actions secret `POSITIONS_JSON`.

- Secret input has priority over the local file.
- Schema is validated before use.
- A present but malformed secret fails closed to an empty portfolio.
- It never falls back to the public example file.
- Exact positions remain in process memory.
- The committed position snapshot contains aggregate health metadata only.

The required schema and update procedure are documented in `docs/positions_schema.md` and `docs/github_secrets_setup.md`.

### Private portfolio risk brief

Every configured EOD position check now sends a silent, private Telegram summary containing:

- estimated account value
- net and gross delta notional
- delta-equivalent shares by symbol
- daily theta
- vega per 1% IV move
- symbol concentration
- theme exposure
- explicit `thesis_id` coverage
- option DTE and delta
- market-data gaps

This detailed payload exists only in memory and Telegram. It is not written to Git, dashboard JSON or Actions artifacts.

### Public-state and log privacy boundary

This repository is public. Exact holdings, strikes, costs, PnL and account values must not be committed or printed in Actions logs.

The position workflow therefore persists only:

- configured / empty status
- input source type
- aggregate position count
- long/short option counts
- timestamp
- privacy marker

Additional controls:

- Position-alert dedup and quota records use HMAC-derived opaque keys instead of `symbol::kind`.
- Account peak/current values are Fernet-encrypted using `POSITION_STATE_KEY`.
- Public drawdown state exposes percentage, alert level, action and timestamp, but not account amounts.
- Sensitive Telegram sends replace the message preview in CI logs with `<sensitive message redacted>`.
- Position workflow suppresses symbol-bearing management/data-library logs.

### Position-monitor correctness fixes

1. `run_position_check.py` previously read `snapshot["total_value"]`, while the snapshot returns `total_estimated_value`; drawdown updates therefore never ran.
2. `leaps_pnl_tracker.py` compared Black–Scholes premium per share with `cost_per_contract` (premium ×100), producing approximately -99% false losses. Both sides now use per-contract USD.
3. Position alerts defaulted to `yellow`, which maps to P2; the router intentionally does not send P2/P3. LEAPS PnL, short-delta and hedge-DTE alerts now map to routable P1, while major drawdowns retain P0 logic.
4. The stale v4 test expected a stock short-premium threshold of IVR 30. The actual v4.1 rule is stock 70 / ETF 30; the test now matches the implemented strategy rule.

## Activation requirement

The code path is complete, but production position monitoring remains intentionally unconfigured until the repository owner creates:

- `POSITIONS_JSON`
- `POSITION_STATE_KEY`

No agent should receive or paste their actual values. The owner sets them directly in GitHub repository Actions secrets and manually runs **Position Management Check** once to validate the redacted state and private Telegram brief.

## Remaining work

### P1 — deeper thesis-linked portfolio risk

- require or flag missing `thesis_id` during private position validation
- add explicit correlated-basket exposure for AI capex and memory subthemes
- add contract-level roll windows and hedge-coverage ratios to the private brief
- compare current exposure with the capital-allocation queue before new capital is reviewed

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
