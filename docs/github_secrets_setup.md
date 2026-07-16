# GitHub Actions secrets setup

## 1. Open repository settings

1. Open the GitHub repository.
2. Select **Settings**.
3. Select **Secrets and variables → Actions**.

Never paste real secret values into issues, PR comments, agent conversations, logs or committed files.

## 2. Required notification secrets

| Name | Purpose |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token used for alerts |
| `TELEGRAM_CHAT_ID` | One or more destination chat IDs |

## 3. Private position monitoring

Create both repository secrets:

| Name | Purpose |
|---|---|
| `POSITIONS_JSON` | Complete private holdings JSON used only during Position Management Check |
| `POSITION_STATE_KEY` | Stable Fernet key used to encrypt account peak/current values before state is committed |

### `POSITIONS_JSON`

The value must follow `docs/positions_schema.md`. Paste the complete JSON object as the secret value. Do not base64-encode it and do not commit it.

Every production position should include an explicit approved `thesis_id`. Missing or invalid decision links do not leak details, but they make Position Management Check return `degraded` with safe generic error codes.

### `POSITION_STATE_KEY`

Generate a Fernet key locally:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Store the printed value exactly as `POSITION_STATE_KEY`. Do not reuse an API token or password.

Rotating or deleting this key makes previous encrypted high-water state unreadable. The next position check will safely reset the drawdown peak to the then-current estimated value.

### Security behavior

- `position_check.yml` injects both values only into the position-check process.
- The position loader validates schema before use.
- A malformed `POSITIONS_JSON` fails closed and never falls back to the public example file.
- Exact holdings and account values stay in memory.
- Position alert dedup/quota keys are HMAC-derived opaque identifiers.
- Account peak/current values are Fernet-encrypted before persistence.
- Public state exposes only aggregate counts/ratios, generic error codes, drawdown percentage, alert level and timestamps.
- Private Telegram contains symbol/basket risk details; sensitive message text, recipients and Bot API URLs are redacted from Actions logs.

## 4. Agent workflow does not require AI API secrets

The canonical workflow deliberately keeps model inference out of GitHub Actions:

- Do **not** create `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` or another model key solely for PR routing/review.
- GitHub Actions performs deterministic CI, capability/source drift checks, ChatOps state transitions and routing-report validation only.
- Codex review uses the authenticated repository integration and verified `@codex review` adapter.
- Claude Fable／Claude Code／other workers receive implementation or review work through an authenticated task surface selected at runtime.
- If no authenticated worker path is available, record `BLOCKED_DELIVERY`; do not invent a GitHub mention or add an inference Action as a workaround.

This repo policy is stricter than the set of integrations that vendors technically support. A future change to add a model inference Action, provider credential, GitHub App permission or paid service requires Kevin's explicit approval and a separate reviewed PR.

## 5. Other currently used product secrets

Depending on enabled workflows, the repository also uses:

- `FRED_API_KEY`
- `SEC_EDGAR_USER_AGENT`
- `GMAIL_SENDER`
- `GMAIL_APP_PASSWORD`
- `EMAIL_RECIPIENT`
- `GEMINI_API_KEY`
- optional `GEMINI_MODEL`

Only add secrets for workflows that are actually enabled.

## 6. Validation

1. Run **Health Check** and confirm the System Online Telegram message.
2. Run **Position Management Check** manually.
3. Confirm `data_store/position_snapshot.json` reports `configured: true` and `privacy: redacted_public_state`.
4. Confirm its `decision_risk.privacy` is `aggregate_decision_risk_only` and contains no ticker/basket names.
5. Confirm `data_store/drawdown_history.json` contains `encrypted_state` and no `peak` or `current` fields.
6. Confirm `alert_dedup.json` / `alert_routing_state.json` use opaque `private-position::...` keys rather than position symbols.
7. Search changed state files for a known private ticker, basket, strike and account amount; none should appear.
8. On a Draft PR, verify `CI`, `Agent Capability Watch`, the live Trump source probe, a current-HEAD `agent-routing-report:v1`, and authenticated non-owner review delivery before asking Kevin for merge authorization.

## Safety rules

- Never write secret values in code, issues, PR comments, logs or committed documentation.
- Never commit a `.env` file.
- Never paste real positions into `data_store/positions.json` in the public repository.
- Rotate a secret immediately if it is exposed.
- Do not grant an agent merge, deploy, Pages, Actions-write or secret-read permissions merely for convenience.
