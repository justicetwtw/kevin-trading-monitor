# GitHub Actions secrets setup

## 1. Open repository settings

1. Open the GitHub repository.
2. Select **Settings**.
3. Select **Secrets and variables → Actions**.

## 2. Required notification secrets

Create these repository secrets:

| Name | Purpose |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token used for alerts |
| `TELEGRAM_CHAT_ID` | One or more destination chat IDs |

## 3. Private position monitoring

Create one additional repository secret:

| Name | Purpose |
|---|---|
| `POSITIONS_JSON` | Complete private holdings JSON used only during the Position Management Check workflow |

The value must follow `docs/positions_schema.md`. Paste the complete JSON object as the secret value. Do not base64-encode it and do not commit it to the repository.

Security behavior:

- `position_check.yml` injects the value only into the position-check process.
- The loader validates the schema before use.
- A malformed secret fails closed to an empty portfolio and never falls back to the public example file.
- Exact holdings and account value stay in memory.
- Only a redacted health snapshot is committed.

## 4. Other currently used secrets

Depending on enabled workflows, the repository also uses:

- `FRED_API_KEY`
- `SEC_EDGAR_USER_AGENT`
- `GMAIL_SENDER`
- `GMAIL_APP_PASSWORD`
- `EMAIL_RECIPIENT`
- `GEMINI_API_KEY`
- optional `GEMINI_MODEL`

Only add secrets for workflows that are actually enabled.

## 5. Validation

1. Run **Health Check** and confirm the System Online Telegram message.
2. Run **Position Management Check** manually.
3. Confirm `data_store/position_snapshot.json` reports `configured: true` and `privacy: redacted_public_state`.
4. Confirm the committed file contains no symbols, strikes, costs, PnL or account value.

## Safety rules

- Never write secret values in code, issues, PR comments, logs or committed documentation.
- Never commit a `.env` file.
- Never paste real positions into `data_store/positions.json` in the public repository.
- Rotate a secret immediately if it is exposed.
