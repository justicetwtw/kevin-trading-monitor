# Codex delivery workflow — Direct task first and same-PR updates

> Status: canonical Codex-specific delivery contract for `kevin-trading-monitor`.
> Last verified against the working workflow in `justicetwtw/jin-yi-yang-bot`: 2026-07-24.
> General ownership, safety, review, privacy and merge rules remain in `AGENTS.md` and `docs/agent-team-workflow.md`.

## 1. Decision

For a **new Codex implementation**, the default route is:

```text
ChatGPT / Kevin finishes the SPEC
→ create a Codex Direct Cloud task from current main
→ give the SPEC directly to that task
→ Codex implements, tests, creates and pushes its own branch
→ operator creates the Draft PR from the Codex UI (`operator_create_pr`)
→ review findings and later updates return to the same task and branch
```

Do **not** use this route:

```text
ChatGPT creates a spec branch or seed Draft PR
→ later asks Codex to take over that existing PR
```

That seed-PR handoff is not the default implementation path. It can leave completed work trapped in a task-local or desktop worktree without a verified same-branch publisher.

The only completion proof is that the intended remote branch and PR HEAD advance and the resulting SHA has visible diff, CI and review evidence.

## 2. New implementation route

### 2.1 Before task creation

The orchestrator must:

1. Read current `main`, open implementation PRs and applicable repo instructions.
2. Confirm no other implementation owner already owns overlapping scope.
3. Write the complete task contract:
   - Goal / Outcome;
   - relevant current facts and dependencies;
   - boundaries and approval limits;
   - acceptance evidence;
   - explicit prohibition on merge, deploy, production workflow activation and broker execution unless separately authorized.
4. Use the latest current `main` as the task starting branch.
5. Provide the SPEC directly in the Codex task. A separate spec PR is unnecessary unless the specification itself is the final product.

### 2.2 Codex task responsibilities

Codex owns one implementation branch and must:

- inspect the repository and verify assumptions before writing;
- implement and test within the authorized scope;
- keep unrelated dirty files and other owners' work untouched;
- create commits on its own branch;
- publish the branch through its task's native publisher;
- report the exact resulting remote 40-character SHA;
- never create a second implementation PR for the same task.

### 2.3 PR creation

After the branch is remotely visible, the operator uses the Codex UI to create the PR. Record this as:

```text
operator_create_pr
```

This is not an autonomous agent PR creation claim. The PR should remain Draft until repository review gates pass.

## 3. Update and repair functionality

An implementation workflow is incomplete unless it can update the same PR after review.

### 3.1 Primary update route: same Codex task

For findings, scope clarifications or follow-up implementation:

```text
read current remote PR metadata and HEAD
→ send the verified finding and exact current HEAD to the original Codex task
→ original task edits the same implementation branch
→ task tests and publishes a non-force update
→ verify the same PR remote HEAD advanced
```

Requirements:

- same original Codex task;
- same implementation branch;
- same PR;
- current remote HEAD, not a historical SHA;
- no replacement branch or replacement PR;
- review only the incremental diff unless architecture changed materially.

A task-local commit, summary, screenshot, receipt or claimed success is not an update. The remote PR HEAD must actually advance.

### 3.2 Fallback update route: authenticated Local Codex owner

When the original task no longer exposes a working `Update PR` publisher, Kevin may explicitly transfer ownership to an authenticated Local Codex session.

The Local owner must follow `docs/local-codex-delivery.md`:

- use a clean clone or isolated worktree;
- fetch the current PR metadata and exact head SHA;
- verify authenticated write access with a non-mutating push dry-run;
- align to the existing PR branch;
- audit, edit, test, commit and non-force push to that same branch;
- re-read GitHub and prove local, remote branch and PR HEAD match.

Publication failure does not authorize a replacement PR.

### 3.3 Ownership transfer

Ownership transfer requires:

- explicit Kevin authorization;
- one outgoing owner and one incoming owner;
- exact PR number, branch and current remote HEAD;
- a clear statement of which local work is authoritative and which is only salvage material;
- no parallel writes after transfer.

## 4. Existing PR and PR-context boundaries

A GitHub PR-context Codex task may be useful for review or bounded fixes, but it is not the default entry for a new implementation.

- Exact `@codex review` is review-only.
- A deliberate non-review Codex PR comment may start a PR-context task, but delivery still requires the original PR HEAD to advance.
- Absence of shell `git remote` or `gh` inside a Cloud sandbox does not by itself prove the native publisher is unavailable.
- Conversely, a task-local commit does not prove publication succeeded.
- A PR-context task only has reliable context for the PR that triggered it; a PR number or SHA alone does not import another private branch snapshot.

## 5. Salvaging local-only work

Local-only candidate work may be reused only after audit.

1. Preserve the original worktree; do not delete or clean it.
2. Treat every untracked file as unreviewed input.
3. Audit for secrets, private positions, account values, local absolute paths, caches, generated payloads and production state.
4. A new Codex Direct task must start from current `main` and create its own branch.
5. The task may compare or selectively port audited local files, but must not claim the old seed PR as delivery evidence.
6. Re-run tests in the new branch and obtain new remote CI.

## 6. Delivery states

Use these states precisely:

- `BLOCKED_CONTEXT`: required repository or PR snapshot is not present and no verified read adapter is available.
- `BLOCKED_DELIVERY`: implementation exists or could proceed, but no verified route can advance the intended remote branch.
- `DELIVERED`: intended remote PR HEAD advanced and the diff is visible.
- `READY_FOR_REVIEW`: delivered SHA has deterministic tests/CI and a current routing report.
- `NEEDS_KEVIN`: independent review passed and the PR is waiting for Kevin's decision.

Never describe local-only work as delivered.

## 7. Review and merge

For implementation PRs:

1. remote HEAD and diff visible;
2. deterministic tests and actual CI on that SHA;
3. SHA-bound `agent-routing-report:v1`;
4. non-owner fresh-context review;
5. material findings fixed or evidence-based rejected;
6. exact tested SHA and residual limitations reported to Kevin;
7. Kevin explicitly authorizes that PR's merge.

Documentation-only workflow maintenance may be authored and merged by ChatGPT through the GitHub connector when Kevin explicitly authorizes that exact documentation PR. This exception does not authorize product code, strategy logic, deployment, production workflow activation or secrets changes.

## 8. Anti-pattern recorded by PR #20

PR #20 used the wrong sequence:

```text
seed spec PR
→ Codex asked to take over the existing PR
→ implementation remained local-only because publication was not established
```

The PR was closed as superseded. Its specification and local work may be used only as audited source material for a new Direct task from current `main`.