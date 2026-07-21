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
