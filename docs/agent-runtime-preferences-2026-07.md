# Agent runtime preferences — 2026-07

> Dated operator preference, not permanent root authority. Re-evaluate when official guidance, product availability, quota, observed quality, latency or delivery paths change.

## Current preference

- Kevin discusses goals, tradeoffs and final acceptance with the strongest available Conversation／Workflow Orchestrator.
- ChatGPT account-level **Ultra** is kept enabled by default when available for high-leverage orchestration and difficult reasoning. This is not a promise of zero cost, not the Work composer effort control, and not a requirement to fan out every task.
- Implementation owner is selected per task from authenticated available workers based on remaining quota, task fit, tools, delivery path and failure mode.
- Lower-cost subagents are preferred only for independent, bounded, verifiable support work where they are expected to save cost, latency or main-thread context.
- A sequential or shared-file-heavy task may correctly use no subagents; the routing report records this explicitly as `subagents_used=false` plus an evidence-backed reason.
- Independent review must be done by a non-owner; use a different provider／model family when practical, but never at the cost of an unverified delivery path.

## Evidence posture

- Product UI／API usage, credits, latency or token metrics are recorded only when the actual surface exposes them.
- When unavailable, routing report uses `status: unavailable` and names the source limitation; it does not estimate or fabricate numbers.
- Model self-report, Bot comment or task-start acknowledgement is not correctness evidence. Remote HEAD, deterministic tests, CI, snapshots and live probes remain authoritative.

## Re-evaluation triggers

- OpenAI／Anthropic changes model availability, reasoning modes, subagents, agent teams, GitHub integration, permissions, quota or pricing semantics.
- A worker cannot update the same PR or return review through an authenticated surface.
- Usage or latency evidence shows the current assignment is wasteful or lower quality.
- Two repair rounds fail, findings conflict, or context degradation becomes material.
- Kevin changes the preferred orchestration or acceptable-cost posture.
