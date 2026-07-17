# Private positions schema

> This repository is public. **Never commit real holdings, symbols, strikes, costs or account value.**

## Runtime source priority

1. `POSITIONS_JSON` — GitHub Actions repository secret used by cloud position checks.
2. `data_store/positions.json` — local-development fallback only.

When `POSITIONS_JSON` exists but is malformed, the loader fails closed to an empty portfolio. It does not fall back to the public example file.

## Modes

`POSITION_MODE` controls whether position data is required:

| Mode | Behavior | Use case |
|---|---|---|
| `mode_1` | Required. Empty/invalid private input or missing/unknown decision links degrades the workflow. | Production position monitoring |
| `mode_2` | Optional; empty input is allowed. | Signal observation with occasional local position checks |
| `mode_3` | Disabled; position getters return empty state and account value is `None`. | Pure signal mode |

The scheduled `position_check.yml` workflow uses `mode_1` and reads `POSITIONS_JSON` only at runtime.

## JSON schema

```json
{
  "stocks": [
    {
      "symbol": "NVDA",
      "shares": 100,
      "avg_cost": 480.50,
      "thesis_id": "ai_capex",
      "_example": false
    }
  ],
  "options": [
    {
      "id": "NVDA_2027C_120",
      "symbol": "NVDA",
      "type": "long_call",
      "strike": 120.0,
      "expiry": "2027-01-15",
      "contracts": 1,
      "cost_per_contract": 4250.0,
      "thesis_id": "ai_capex",
      "_example": false
    }
  ]
}
```

### `stocks[]`

- `symbol` — required, non-empty ticker string.
- `shares` — required numeric quantity, zero or greater.
- `avg_cost` — optional numeric average cost.
- `thesis_id` — **required for healthy production decision monitoring**. It must exactly match an existing theme or subtheme ID in `data_store/thesis_tracker.json`.
  - empty/missing → safe code `position_thesis_id_missing`;
  - non-empty but unknown → safe code `position_thesis_id_invalid`.
- `_example` — optional boolean; `true` is ignored.

### `options[]`

- `symbol` — required underlying ticker.
- `type` — one of `long_call`, `long_put`, `short_call`, `short_put`.
- `strike` — required positive number.
- `expiry` — required `YYYY-MM-DD` date.
- `contracts` — optional positive integer, default `1`.
- `cost_per_contract` — numeric **whole-contract cost in USD** (`premium per share × 100`). Required for LEAPS PnL monitoring.
- `id` — recommended stable identifier.
- `thesis_id` — **required for healthy production decision monitoring**. Portfolio hedges should use an explicit approved hedge thesis such as `portfolio_hedge`, not inherit an issuer thesis.
- `_example` — optional boolean; `true` is ignored.

Schema validation still accepts a missing or unknown `thesis_id` so legacy data cannot crash the loader, but the position workflow fails closed to `degraded` until the decision link is repaired. This separates transport/schema validity from decision-model completeness.

## Private decision-risk output

The private Telegram portfolio brief now includes:

- symbol and theme Delta exposure;
- overlapping correlation baskets such as `ai_capex`, `memory_cycle`, `hbm`, `commodity_dram`, `nand`, `optical_interconnect` and `portfolio_hedge`;
- protective negative Delta（only long puts / short stock；short calls are Delta offset, not downside protection）divided by positive Delta, plus a separate total Delta-offset ratio;
- option roll counts at ≤90, ≤180 and ≤270 days;
- missing/invalid thesis IDs, unmapped basket coverage and review flags.

The current 50% correlated-basket threshold is labeled `repo_default_pending_kevin_confirmation`. It is a review gate, not an automatic trim instruction. Basket gross weights overlap and may sum above 100%; they are factor lenses, not allocation slices.

## Public-state boundary

During a position workflow run, exact positions and estimated account value exist only in memory. The committed `data_store/position_snapshot.json` may contain only:

- mode and source type;
- configured/empty status;
- aggregate position and long/short option counts;
- valuation completeness counts;
- workflow status, generic error codes and timestamp;
- aggregate decision-risk counts/ratios:
  - missing thesis ID count;
  - invalid thesis ID count;
  - unmapped-position count;
  - maximum basket gross-weight ratio;
  - hedge-coverage ratio;
  - roll-window counts;
  - generic review flags.

It must never contain symbols, shares, basket names, strikes, expiries, costs, PnL, account value or detailed Greeks. Tests serialize the public decision-risk state and assert private symbols/basket names are absent.

## Updating the GitHub secret

Open repository **Settings → Secrets and variables → Actions → New repository secret** and set:

- Name: `POSITIONS_JSON`
- Value: the complete valid JSON object shown above, with real values and no comments.

After updating, manually run **Position Management Check** once. Confirm the public health snapshot says `configured` without exposing position details, and confirm none of these safe errors remain:

- `position_thesis_id_missing`
- `position_thesis_id_invalid`
- `position_correlation_basket_unmapped`

## Local development

For local-only testing, copy the same JSON to `data_store/positions.json`. Keep the file untracked and verify it is ignored before entering real data.

To reset the one-time `mode_1` warning locally, delete `data_store/mode1_warned.flag`.

## Hedge recognition

`hedge_dte_tracker` treats either condition as a hedge:

- a long option on an `ETF_HEDGE` symbol such as `QQQ`, `SPY`, `SMH` or `SOXL`;
- any `long_put`.

Recognition is not proof of economic effectiveness. Basis risk, expiry mismatch, liquidity and intended-alpha preservation remain human review items.
