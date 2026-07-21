# Market Brief SLA & Delivery Reliability v1

Status: implementation contract for Issue #13  
Owner: Claude / Opus as the sole implementation owner  
Rollout: draft first; no merge or production activation without Kevin approval

## 1. Incident and objective

On 2026-07-20 the U.S. regular session opened at 21:30 Asia/Taipei, but the `us_open` brief was only marked sent at about 23:25, roughly 115 minutes late. A message arriving that late cannot honestly be presented as an opening brief.

The objective is to make U.S. opening briefs:

- timely enough to be useful;
- resilient to delayed or reordered GitHub scheduled runs;
- idempotent per U.S. session;
- observable without exposing Telegram content or secrets;
- honest when delivery is late.

This PR must remain separate from Focus Engine PR #10, Trump translation Issue #11, Estimates Provider work, and Focus Telegram work.

## 2. Product timing contract

Canonical clock:

- U.S. regular open: 09:30 America/New_York.
- Asia/Taipei equivalent: 21:30 during U.S. daylight time; 22:30 during standard time.
- Session identity: `us_open:<YYYY-MM-DD ET>`.

SLA classes:

- `on_time`: sent from market open through +10 minutes.
- `late`: sent after +10 and through +30 minutes.
- `intraday_recovery`: sent after +30 minutes while the regular session remains open.
- `expired`: the regular session has closed; do not send an opening brief.

The thresholds must be constants with deterministic tests, not hidden in copy strings.

## 3. Scheduling architecture

Do not retain the current design where daylight/standard primary and backup schedules all share one broad `market-brief` concurrency queue.

Implement a dedicated U.S.-open watchdog path with these properties:

1. It is isolated from EOD, Taiwan, premarket and midday briefs.
2. It uses multiple staggered attempts around both possible DST/standard windows; avoid relying on a single exact-hour cron.
3. Every attempt computes the current New York session at runtime. A cron expression must never be treated as proof of DST or market phase.
4. Runs are serialized for the U.S.-open delivery path so two attempts cannot send concurrently.
5. A later pending attempt must not silently eliminate the only valid earlier attempt. Document the selected concurrency semantics and prove them with workflow-level tests or deterministic model tests.
6. The runner is the source of truth for whether the current attempt is early, in-window, late, expired, duplicate or wrong-session.

GitHub Actions scheduled workflows have no hard punctuality SLA. If a verified <=5–10 minute delivery guarantee is required, the implementation report must explicitly state whether GitHub-only scheduling can meet it. An external scheduler or persistent runner may be proposed, but no service, credential or paid dependency may be added without Kevin approval.

## 4. Delivery state and idempotency

A boolean `brief_sent_today.json` entry is insufficient. Replace or migrate it to a session-scoped state machine.

Minimum state fields:

```json
{
  "schema_version": 1,
  "brief_type": "us_open",
  "session_date_et": "YYYY-MM-DD",
  "session_key": "us_open:YYYY-MM-DD",
  "expected_at_taipei": "ISO-8601",
  "workflow_started_at": "ISO-8601",
  "generation_started_at": "ISO-8601|null",
  "generation_finished_at": "ISO-8601|null",
  "sent_at": "ISO-8601|null",
  "lateness_minutes": 0,
  "schedule_source": "cron expression or workflow_dispatch",
  "workflow_run_id": "opaque value",
  "delivery_state": "claimed|sent|failed|ambiguous|skipped",
  "status": "on_time|late|intraday_recovery|expired|failed|skipped_duplicate|skipped_wrong_session",
  "stage_code": "generic code|null"
}
```

Requirements:

- One successful Telegram delivery at most per `session_key`.
- Serialize attempts and persist a claim before the outbound send.
- Persist Telegram success immediately after sending, with retry/rebase handling for state-write conflicts.
- Do not store message text, chat ID, token or private portfolio details.
- A crash between Telegram success and final state persistence is a distributed-systems ambiguity. Do not falsely claim perfect exactly-once delivery. Mark or surface `ambiguous_delivery`; do not automatically create an uncontrolled duplicate.
- Failed Telegram sends remain retryable during the valid session window.
- Provide backward migration for the existing boolean dedup state.

## 5. User-facing semantics

The title and body must reflect actual delivery phase:

- On time: `🚀 美股開盤 brief`.
- Late: `⚠️ 美股開盤 brief 延遲補發（晚 X 分鐘）`.
- Intraday recovery: `⚠️ 美股盤中補發（原開盤 brief 晚 X 分鐘）`.
- Expired: do not send an opening brief.

The data snapshot and market phase must be recomputed when the workflow actually runs. A 23:25 delivery cannot reuse copy or assumptions captured for 21:30.

Mission Control or a public-safe health state must show delivery health and lateness. Telegram content remains private.

## 6. Failure and health semantics

Use generic, stage-specific codes such as:

- `schedule_delay`
- `wrong_session_window`
- `duplicate_session`
- `claim_conflict`
- `generation_failed`
- `telegram_send_failed`
- `state_persist_failed`
- `ambiguous_delivery`

A workflow must not finish green while a required send failed or delivery state is ambiguous. Wrong-session and duplicate skips may finish successfully if their reason is explicitly recorded.

## 7. Required tests

Deterministic tests must cover at least:

- U.S. daylight and standard dates.
- 21:30/22:30 exact open, +5, +15, +35, 23:25 and after-close execution.
- Primary delayed; watchdog/backup runs first.
- Runs arrive out of chronological order.
- Multiple pending attempts and serialization semantics.
- Same session attempts send no more than once.
- Telegram failure followed by a valid retry.
- Telegram success followed by state persistence conflict.
- Ambiguous delivery is surfaced rather than silently duplicated.
- Legacy boolean dedup migration.
- Manual dispatch within and outside the valid window.
- User-facing title, market phase and lateness are correct.
- No Telegram content, secret or private holdings enter public state, logs or artifacts.

Validation before review:

```bash
python -m pytest -q
python scripts/verify_agent_workflow_contract.py
python scripts/agent_capability_watch.py --config .github/agent-capability-watch.json --offline
```

Current-head GitHub Actions CI must be green.

## 8. Rollout and boundaries

- Keep the PR Draft while implementing.
- Do not change Focus Engine, Trump translation or Estimates code.
- Do not add a new service, secret, plugin, MCP or paid API.
- Preserve current briefs until the new U.S.-open path is proven by tests.
- Include rollback instructions to restore the previous workflow and state reader.
- Do not merge, deploy or activate revised production scheduling without Kevin's explicit authorization.

## 9. Implementation handoff

Claude / Opus remains the sole implementation owner on branch `claude/issue-13-market-brief-sla`.

Before requesting review:

1. implement code and deterministic regressions, not only documentation;
2. update this document if an assumption changes;
3. run the full validation suite and obtain current-head CI;
4. add an exact-HEAD `agent-routing-report:v1`;
5. report each acceptance item as fixed, intentionally degraded with evidence, or blocked;
6. keep the PR Draft and stop for an independent incremental review.

## 10. Implementation status (v1, hardened per incremental review)

Delivered on this branch:

- `src/runners/us_open_sla.py` — deterministic session resolution, SLA
  classification (`on_time`/`late`/`intraday_recovery`/`expired`) with named
  minute thresholds, phase-aware body selection and honest title/copy.
- `src/runners/us_open_state.py` — session-keyed delivery state machine
  (`data_store/us_open_delivery_state.json`, section-4 schema) with
  claim/sent/failed/ambiguous/skipped/observing states, **atomic writes**
  (temp + fsync + `os.replace`), **fail-closed** reads (a corrupt file is never
  read as empty), no-downgrade of `sent`, no-erasure of `failed`, bounded
  per-session attempt telemetry, retention pruning, and **date-gated** legacy
  migration.
- `src/runners/run_us_open_brief.py` — the runner: recompute NY session →
  fail-closed state read → idempotency/ambiguity check → regenerate a
  phase-appropriate body → **durably push the claim before the send** → send →
  persist outcome. Fails closed (exit 1) on send failure, ambiguity, expiry
  miss, generation failure or unreadable state.
- `src/alerts/telegram_bot.py` — `send_telegram_detailed` returns a tri-state
  outcome so the runner distinguishes a definitive rejection (retryable) from an
  ambiguous timeout/partial delivery (surfaced, never auto-retried). The
  existing `send_telegram` bool contract is unchanged for other briefs.
- `.github/workflows/us_open_brief.yml` — dedicated, isolated watchdog; captures
  the real workflow-start time before setup; enables the durable claim push.
- `market_brief.yml` no longer schedules or dispatches `us_open`.
- `run_brief_sanity.py` reads `us_open` completion from the new state (or the
  legacy boolean) so the nightly check stays accurate.

### Concurrency & at-most-once (documented, not hidden)

The dedicated group serializes attempts (no two send concurrently). At-most-once
does **not** rely on GitHub's pending queue surviving:

- The runner reads durable state and **durably commits+pushes its `claimed`
  record to `main` before the outbound send** (runner git op, retried; a
  transient failure is flushed by the trailing `commit-state`).
- Therefore a dropped/replaced pending attempt can cause neither a **duplicate**
  (serialization + a durable claim that the next attempt observes → ambiguous,
  no resend) nor a **miss** (later staggered crons re-cover from durable state).
- Wrong-DST attempts self-skip before open or become a guarded recovery; the
  runtime NY-session computation, not the cron label, decides.
- A crash between the durable claim and the send resolution is a genuine
  exactly-once ambiguity: surfaced as `ambiguous_delivery` (workflow red),
  never auto-duplicated, and it stays red until the record is cleared.
- Expiry semantics: a completely missed opening brief exits **red** and records
  the miss; an expiry after a prior send failure preserves the `failed` state
  and its stage code rather than overwriting it with a benign skip.

### Observability

`workflow_started_at` is captured by the first workflow step (before Python
setup/install) so GitHub queue delay is separable from runner/setup delay;
`runner_started_at`, `generation_started_at/finished_at` and `sent_at` isolate
the remaining stages. Every attempt — including early/duplicate/expired skips —
appends a bounded generic entry to `observed_attempts`, so diagnosis is durable,
not log-only.

### GitHub scheduling honesty & residual limitations

- GitHub `schedule` has no punctuality guarantee and can delay/drop runs, so a
  GitHub-only design cannot promise a hard ≤5–10 minute delivery SLA. This makes
  late delivery *honest and observable* rather than pretending punctuality. A
  verified tight SLA needs an external scheduler / persistent runner — **not**
  added here (no new service/credential without Kevin approval).
- **Exchange holidays are not detected** (that needs an exchange-calendar
  source, deferred as out of scope). Only weekends are treated as non-trading;
  on a U.S. holiday a scheduled attempt would classify as a normal in-window
  send.
- The durable claim narrows, but cannot fully eliminate, the exactly-once
  window: a crash after the send but before either the runner's claim push or
  the trailing `commit-state` completes still leaves a small residual, which is
  by design surfaced as ambiguity rather than silently duplicated.

### Public-safe health

`data_store/us_open_delivery_state.json` contains only timestamps, session
keys, statuses, lateness and generic stage codes — never Telegram content, chat
IDs, tokens or portfolio data — so the committed file is itself the public-safe
delivery-health surface. `UsOpenDeliveryStore.public_health()` exposes it.

### Rollback

To restore the previous behaviour without losing history:

1. Re-add the `us_open` crons (`30 13`/`0 14` daylight, `30 14`/`0 15`
   standard), the `us_open` DST case branches and the `us_open` dispatch option
   to `market_brief.yml`.
2. Delete (or disable) `.github/workflows/us_open_brief.yml`.
3. Revert `run_brief_sanity.py` to read `us_open` from `brief_sent_today.json`.
4. `data_store/us_open_delivery_state.json` can be left in place (ignored by the
   old path) or removed; the legacy `brief_sent_today.json` boolean is never
   deleted by the new path, so the old reader keeps working.
