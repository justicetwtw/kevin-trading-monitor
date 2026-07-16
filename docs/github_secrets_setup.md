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

Every production position should include an explicit `thesis_id`. Missing decision links do not leak details, but they make Position Management Check return `degraded` with the safe code `position_thesis_id_missing`.

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

## 4. Claude independent review workflow

The new `.github/workflows/claude_review.yml` is deliberately separate from deterministic CI. It only runs for a trusted OWNER/MEMBER/COLLABORATOR who posts this exact PR comment:

```text
@claude review <complete 40-character current remote HEAD SHA>
```

Create this repository secret only when the Claude review workflow is intentionally enabled:

| Name | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Authenticates `anthropics/claude-code-action@v1` for fresh-context, review-only PR analysis |

Required activation checks:

1. Install/authorize the official Claude GitHub App if the selected setup requires it.
2. Add `ANTHROPIC_API_KEY` under **Actions repository secrets**.
3. Keep workflow permissions at contents read + issues/PR write only.
4. Trigger a test review on a Draft PR using the exact current SHA.
5. Confirm the workflow posts a real `PASS`, `CHANGES_REQUIRED` or `BLOCKED` review and does not edit code, merge, deploy or expose secrets.

If the secret is absent, SHA is stale, actor is untrusted or the PR is closed, the workflow must report/reject the request rather than pretend a review ran. A Claude pass only moves the PR toward `needs-kevin`; it never authorizes merge.

Do not store an Anthropic key in Codex/ChatGPT conversation text or use it for implementation tasks that Kevin did not request.

## 5. Other currently used secrets

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
6. Confirm `alert_dedup.json` / `alert_routing_state.json` use `private-position::...` keys rather than position symbols.
7. Search changed state files for a known private ticker, basket, strike and account amount; none should appear.
8. On a Draft PR, verify `CI`, `Agent Capability Watch` and the live Trump source probe. Then test exact-SHA Codex/Claude review delivery before asking Kevin for merge authorization.

## Safety rules

- Never write secret values in code, issues, PR comments, logs or committed documentation.
- Never commit a `.env` file.
- Never paste real positions into `data_store/positions.json` in the public repository.
- Rotate a secret immediately if it is exposed.
- Do not grant an AI review action merge, deploy, Pages, Actions-write or secret-read permissions merely for convenience.
