<!-- shared-agent-workflow-contract:v1 -->
```json
{
  "schema": "shared-agent-workflow-contract:v1",
  "contract_version": "2026-07-24.1",
  "authority": {
    "repository": "justicetwtw/jin-yi-yang-bot",
    "ref": "main",
    "path": "docs/shared-agent-workflow-contract.md"
  },
  "consumers": [
    "justicetwtw/jin-yi-yang-bot",
    "justicetwtw/kevin-trading-monitor"
  ],
  "portable_scope": [
    "new_task_routing",
    "existing_pr_update",
    "remote_delivery_evidence",
    "review_and_merge_gates",
    "cross_pr_context",
    "production_boundaries"
  ]
}
```

# Shared Agent Workflow Contract

This file is the byte-identical, cross-repository contract for workflow rules that are portable between `jin-yi-yang-bot` and `kevin-trading-monitor`. Repository-specific domain, safety, test and production rules remain in each repository's own `AGENTS.md` and workflow documents.

## 1. Authority and synchronization

- `justicetwtw/jin-yi-yang-bot` is the canonical source for this portable contract because its agent workflow is updated more frequently.
- Both repositories retain an exact copy of this file.
- Cross-repository automation compares the exact normalized bytes, metadata version and SHA-256 digest.
- The source repository checks whether the consumer is stale.
- The consumer repository checks the source and creates a Draft synchronization PR when drift is detected.
- Authority is intentionally one-way; comparison and visibility are two-way. This prevents conflicting automatic edits.

## 2. New Codex implementation

The default route for a new Codex coding task is:

```text
complete SPEC
→ Codex Direct Cloud task from current main
→ SPEC is provided directly to that task
→ Codex implements, tests, creates and publishes its own branch
→ operator creates the Draft PR from the Codex UI (`operator_create_pr`)
```

Do not create a seed/spec PR and later ask Codex to take over that existing PR, unless the specification itself is the final deliverable.

## 3. Existing PR updates

Review findings, scope clarifications and follow-up implementation return to the original implementation task:

```text
read current PR metadata and exact remote HEAD
→ original task
→ same branch repair and tests
→ same PR remote HEAD advances
→ incremental review
```

Requirements:

- same implementation task when its publisher is available;
- same branch and same PR;
- current remote HEAD, never a historical SHA;
- non-force publication;
- no replacement PR because publication failed.

When the original task no longer exposes a working update publisher, Kevin may explicitly transfer ownership to an authenticated Local Codex owner. The Local owner must use an isolated worktree, verify the exact current PR HEAD and authenticated push path, and push to the same PR branch.

## 4. Delivery evidence

The following do not prove delivery:

- task-local commit;
- local worktree diff;
- summary or screenshot;
- task receipt or reaction;
- baseline CI from a SHA before the implementation.

Delivery requires:

- intended remote branch and PR HEAD actually advance;
- implementation diff is visible on GitHub;
- deterministic tests and actual CI are tied to the new SHA;
- limitations and blockers are reported honestly.

## 5. Review and merge

- A branch has one implementation owner at a time.
- Independent review must not be performed by the implementation owner.
- Findings are inputs to verify, not automatic truth.
- Repairs return to the original owner and branch.
- Review pass means the PR may be returned to Kevin; it does not authorize merge.
- Merge requires Kevin's explicit authorization for that PR and current SHA.

## 6. Cross-PR and context boundaries

- A PR-context task has reliable context only for the PR that triggered it.
- A PR number or commit SHA identifies a snapshot but does not import another branch's code into the current checkout.
- Missing required snapshots without a verified read adapter is `BLOCKED_CONTEXT`.
- Existing implementation without a verified publication path is `BLOCKED_DELIVERY`.
- Neither condition authorizes a replacement PR.

## 7. Safety and production boundaries

Unless separately authorized for the exact operation, implementation or workflow maintenance does not authorize:

- force push;
- Ready transition or merge;
- deploy or production workflow activation;
- real migration or production data access/write;
- secret, credential, plugin, MCP or paid-service changes;
- broker execution or automated orders.

## 8. Source-maintenance rule

When the canonical source repository changes portable rules in its core agent workflow documents, the source must update this file and increment `contract_version` in the same PR. The source-side guard fails closed when a watched portable-policy file changes without a contract update.