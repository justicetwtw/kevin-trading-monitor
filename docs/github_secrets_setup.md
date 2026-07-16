# GitHub Actions secrets setup

## 1. Open repository settings

1. Open the GitHub repository.
2. Select **Settings**.
3. Select **Secrets and variables → Actions**.

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
- Public state exposes only aggregate counts, drawdown percentage, alert level and timestamps.

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
4. Confirm `data_store/drawdown_history.json` contains `encrypted_state` and no `peak` or `current` fields.
5. Confirm `alert_dedup.json` / `alert_routing_state.json` use `private-position::...` keys rather than position symbols.
6. Search the changed state files for a known private ticker, strike and account amount; none should appear.

## Safety rules

- Never write secret values in code, issues, PR comments, logs or committed documentation.
- Never commit a `.env` file.
- Never paste real positions into `data_store/positions.json` in the public repository.
- Rotate a secret immediately if it is exposed.
