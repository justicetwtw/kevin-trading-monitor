# Private positions schema

> This repository is public. **Never commit real holdings, strikes, costs or account value.**

## Runtime source priority

1. `POSITIONS_JSON` — encrypted GitHub Actions repository secret used by cloud position checks.
2. `data_store/positions.json` — local-development fallback only.

When `POSITIONS_JSON` exists but is malformed, the loader fails closed to an empty portfolio. It does not fall back to the public example file.

## Modes

`POSITION_MODE` controls whether position data is required:

| Mode | Behavior | Use case |
|---|---|---|
| `mode_1` | Required. Empty/invalid private input triggers one warning and the system continues with an empty portfolio. | Production position monitoring |
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
- `thesis_id` — recommended link to `data_store/thesis_tracker.json`.
- `_example` — optional boolean; `true` is ignored.

### `options[]`

- `symbol` — required underlying ticker.
- `type` — one of `long_call`, `long_put`, `short_call`, `short_put`.
- `strike` — required positive number.
- `expiry` — required `YYYY-MM-DD` date.
- `contracts` — optional positive integer, default `1`.
- `cost_per_contract` — numeric **whole-contract cost in USD** (`premium per share × 100`). Required for LEAPS PnL monitoring.
- `id` — recommended stable identifier.
- `thesis_id` — recommended thesis link.
- `_example` — optional boolean; `true` is ignored.

## Public-state boundary

During a position workflow run, exact positions and estimated account value exist only in memory. The committed `data_store/position_snapshot.json` may contain only:

- mode and source type
- configured/empty status
- aggregate position count
- long/short option counts
- snapshot timestamp
- privacy marker

It must never contain symbols, shares, strikes, expiries, costs, PnL or account value.

## Updating the GitHub secret

Open repository **Settings → Secrets and variables → Actions → New repository secret** and set:

- Name: `POSITIONS_JSON`
- Value: the complete valid JSON object shown above, with real values and no comments.

After updating, manually run **Position Management Check** once. Confirm the public health snapshot says `configured` without exposing any position details.

## Local development

For local-only testing, copy the same JSON to `data_store/positions.json`. Keep the file untracked and verify it is ignored before entering real data.

To reset the one-time `mode_1` warning locally, delete `data_store/mode1_warned.flag`.

## Hedge recognition

`hedge_dte_tracker` treats either condition as a hedge:

- a long option on an `ETF_HEDGE` symbol such as `QQQ`, `SPY`, `SMH` or `SOXL`
- any `long_put`
