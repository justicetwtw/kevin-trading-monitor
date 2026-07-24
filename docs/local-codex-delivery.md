# Local Codex delivery and existing-PR continuity

> Status: canonical Local Codex publication contract for `kevin-trading-monitor`.
> Last verified workflow basis: 2026-07-24.
> This file is the fallback/update surface for an existing PR; new Codex implementations default to `docs/codex-delivery-workflow.md`.

## 1. Purpose

Local Codex is used when:

- an existing implementation PR must be updated;
- the original Codex Cloud task no longer exposes a verified `Update PR` publisher;
- Kevin explicitly transfers implementation ownership;
- a local-only candidate worktree must be audited and salvaged.

It is not a reason to open a replacement PR.

## 2. Hard requirements

Before any edit, test or local commit:

1. Use a clean clone or an isolated clean worktree.
2. Do not stash, clean, reset, overwrite or delete an unrelated dirty checkout.
3. Read the existing PR metadata from GitHub.
4. Obtain the exact current 40-character PR head SHA.
5. Confirm the PR is still open and the branch is the authorized delivery target.
6. Verify GitHub authentication for the same Windows user.
7. Verify a non-mutating push dry-run succeeds to the exact existing branch.
8. Confirm only one implementation owner controls the branch.

If any requirement fails, stop before writing and report `BLOCKED_DELIVERY`.

## 3. Windows preflight

From the isolated repository path:

```powershell
git status --short --branch
git remote -v
git fetch origin --prune
gh auth status --hostname github.com

gh pr view <PR_NUMBER> `
  --repo justicetwtw/kevin-trading-monitor `
  --json number,state,isDraft,headRefName,headRefOid,commits,url
```

Align to the exact current remote head. Detached HEAD is acceptable when the push target is explicit:

```powershell
git switch --detach origin/<PR_HEAD_BRANCH>
git rev-parse HEAD
git status --short --branch

git push --dry-run `
  origin `
  HEAD:refs/heads/<PR_HEAD_BRANCH>
```

Required result:

- local HEAD equals `headRefOid`;
- working tree is clean before the repair starts;
- dry-run succeeds;
- PR number and branch match the task contract;
- the observed remote SHA is current, not historical.

## 4. Review-repair loop

For every repair round:

1. Reviewer reads the current remote diff and current PR head.
2. Orchestrator verifies each finding and sends the exact current SHA to the implementation owner.
3. Local Codex fetches and realigns before editing.
4. Local Codex independently validates the finding against code, tests and evidence.
5. Only verified fixes are implemented.
6. Run targeted tests and relevant regressions.
7. Audit the staged file list; do not blindly stage unrelated or untracked files.
8. Commit and non-force push to the same PR branch.
9. Re-read GitHub and require local HEAD, remote branch HEAD and PR head SHA to match.
10. Review the incremental diff against the new SHA.

Never reuse an old SHA as the next round's baseline.

## 5. Staging and privacy audit

Before staging, check all changed and untracked files for:

- `.env`, tokens, credentials, auth caches and chat IDs;
- exact private positions, strikes, contracts, costs, account values and private Greeks;
- local absolute paths and user-profile paths;
- virtual environments, caches, temporary test output and probe artifacts;
- generated public payloads containing private state;
- production snapshots or source responses that should not be committed;
- files belonging to another task or the user's original checkout.

Stage only intentional files. Do not use `git add -A` without first proving every path belongs to the task.

## 6. Push and delivery proof

After commit:

```powershell
git push origin HEAD:refs/heads/<PR_HEAD_BRANCH>

gh pr view <PR_NUMBER> `
  --repo justicetwtw/kevin-trading-monitor `
  --json state,isDraft,headRefName,headRefOid,commits,url
```

Delivery is complete only when:

- push succeeded without force;
- the existing PR remains the delivery target;
- the remote PR head advanced;
- the returned SHA is 40 characters;
- the GitHub diff contains the implementation;
- CI runs on the new SHA.

A local commit, summary, screenshot, task receipt or baseline CI is not delivery proof.

## 7. Authentication failure

An invalid `GH_TOKEN`, expired GitHub CLI session or missing write permission is a delivery blocker.

Do not:

- create a replacement branch or PR;
- copy tokens into chat, logs or files;
- continue producing large local-only edits after the blocker is known;
- claim the code was delivered because local tests passed.

Preserve the worktree and report:

- repository;
- PR number;
- target branch;
- expected remote SHA;
- local HEAD;
- working-tree status;
- exact authentication or permission error;
- confirmation that no stage, commit, push, merge or deployment occurred after the blocker.

## 8. Local salvage into a new Direct task

When work was produced under the wrong seed-PR route:

1. Keep the local worktree untouched as salvage material.
2. Close the superseded seed PR; do not merge it.
3. Start a new Codex Direct task from current `main` with the complete SPEC.
4. Tell the task the salvage worktree is untrusted read-only input.
5. Audit and selectively port files into the new task-owned branch.
6. Re-run all tests and source probes.
7. Publish the new branch and create the Draft PR through `operator_create_pr`.
8. Future updates return to that same original task and branch.

## 9. Boundaries

Local Codex ownership does not authorize:

- force push;
- merge or Ready transition without Kevin's explicit authorization;
- deploy, Pages switch or production workflow activation;
- new secret/plugin/MCP/service installation;
- production data access or writes;
- broker execution or automated orders.