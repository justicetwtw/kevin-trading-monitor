#!/usr/bin/env python3
"""Fail CI when durable multi-agent governance contracts drift."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED = {
    "AGENTS.md": [
        "current remote HEAD",
        "quota",
        "authenticated delivery path",
        "agent-routing-report:v1",
        "CHANGES_REQUIRED",
        "BLOCKED_DELIVERY",
        "needs-kevin",
        "not_decision_grade",
        "只有 Kevin 對該 PR 明確說可 merge 後才可合併",
        "不持有 OpenAI／Anthropic API key",
    ],
    "CLAUDE.md": ["@AGENTS.md", "Independent review"],
    "docs/agent-team-workflow.md": [
        "40-character",
        "quota／availability",
        "agent-routing-report:v1",
        "subagents_used=false",
        "@codex review",
        "BLOCKED_DELIVERY",
        "Review pass",
        "Kevin",
    ],
    "docs/agent-runtime-preferences-2026-07.md": [
        "Dated operator preference",
        "Ultra",
        "subagents_used=false",
        "Re-evaluation triggers",
    ],
    ".github/workflows/agent_chatops.yml": [
        "/agent-review-pass",
        "current remote HEAD",
        "not merge authorization",
        "([0-9a-fA-F]{40})",
        '[ "$supplied" != "$head" ]',
        "verify_agent_routing_report.py",
        "agent-routing-report:v1",
        "contents/scripts/verify_agent_routing_report.py?ref=$head",
    ],
    "scripts/verify_agent_routing_report.py": [
        "agent-routing-report:v1",
        "head_sha",
        "subagents_used",
        "relative_model_tier",
        "usage_evidence",
        "lead_reverification",
        "ci.status must be pass",
        "TRUSTED_ASSOCIATIONS",
    ],
}

FORBIDDEN_ROOT_PATTERNS = [
    "auto-merge after review",
    "review pass authorizes merge",
    "ignore previous instructions",
]

FORBIDDEN_CHATOPS_PATTERNS = [
    "{7,40}",
    'case "$head" in "$supplied"*',
    "actions/checkout",
    "anthropics/claude-code-action",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
]

FORBIDDEN_AI_WORKFLOW_PATTERNS = [
    "anthropics/claude-code-action",
    "openai/codex-action",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
]


def verify(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    loaded: dict[str, str] = {}
    for relative, phrases in REQUIRED.items():
        path = root / relative
        if not path.exists():
            errors.append(f"missing required file: {relative}")
            continue
        text = path.read_text(encoding="utf-8")
        loaded[relative] = text
        for phrase in phrases:
            if phrase.lower() not in text.lower():
                errors.append(f"{relative}: missing contract phrase {phrase!r}")

    agents = loaded.get("AGENTS.md", "")
    for pattern in FORBIDDEN_ROOT_PATTERNS:
        if pattern.lower() in agents.lower():
            errors.append(f"AGENTS.md: forbidden pattern {pattern!r}")

    chatops = loaded.get(".github/workflows/agent_chatops.yml", "")
    for pattern in FORBIDDEN_CHATOPS_PATTERNS:
        if pattern.lower() in chatops.lower():
            errors.append(
                f".github/workflows/agent_chatops.yml: forbidden pattern {pattern!r}"
            )

    claude_workflow = root / ".github" / "workflows" / "claude_review.yml"
    if claude_workflow.exists():
        errors.append(
            ".github/workflows/claude_review.yml must not exist; use authenticated "
            "worker task surfaces rather than repo AI inference Actions"
        )

    workflows_dir = root / ".github" / "workflows"
    if workflows_dir.exists():
        for path in workflows_dir.glob("*.y*ml"):
            text = path.read_text(encoding="utf-8")
            for pattern in FORBIDDEN_AI_WORKFLOW_PATTERNS:
                if pattern.lower() in text.lower():
                    errors.append(
                        f"{path.relative_to(root)}: forbidden AI inference/secret "
                        f"pattern {pattern!r}"
                    )

    claude = root / "CLAUDE.md"
    if claude.exists() and claude.stat().st_size > 3000:
        errors.append(
            f"CLAUDE.md must remain thin; observed {claude.stat().st_size} bytes"
        )
    return errors


def main() -> int:
    errors = verify()
    if errors:
        print("Agent workflow contract verification FAILED:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Agent workflow contract verification passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
