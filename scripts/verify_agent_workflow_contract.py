#!/usr/bin/env python3
"""Fail CI when durable multi-agent governance contracts drift."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED = {
    "AGENTS.md": [
        "current remote HEAD",
        "CHANGES_REQUIRED",
        "BLOCKED",
        "needs-kevin",
        "not_decision_grade",
        "Kevin",
        "只有 Kevin 對該 PR 明確說可 merge 後才可合併",
    ],
    "CLAUDE.md": ["@AGENTS.md", "Independent review"],
    "docs/agent-team-workflow.md": [
        "40-character",
        "@codex review",
        "@claude review",
        "Review pass",
        "Kevin",
    ],
    ".github/workflows/agent_chatops.yml": [
        "/agent-review-pass",
        "current remote HEAD",
        "not merge authorization",
        "([0-9a-fA-F]{40})",
        "[ \"$supplied\" != \"$head\" ]",
    ],
    ".github/workflows/claude_review.yml": [
        "anthropics/claude-code-action@e90deca47693f9457b72f2b53c17d7c445a87342",
        "ANTHROPIC_API_KEY",
        "author_association",
        "40-character",
        "Review only",
        "--allowedTools \"Read,Glob,Grep\"",
        "HAS_ANTHROPIC_KEY",
    ],
}

FORBIDDEN_ROOT_PATTERNS = [
    "auto-merge after review",
    "review pass authorizes merge",
    "ignore previous instructions",
]

FORBIDDEN_WORKFLOW_PATTERNS = {
    ".github/workflows/agent_chatops.yml": [
        "{7,40}",
        'case "$head" in "$supplied"*',
    ],
    ".github/workflows/claude_review.yml": [
        "ANTHROPIC_KEY: ${{ secrets.ANTHROPIC_API_KEY }}",
        "anthropics/claude-code-action@v1",
        '--allowedTools "Bash',
        "contents: write",
        "actions: write",
        "deployments: write",
    ],
}


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
                errors.append(
                    f"{relative}: missing contract phrase {phrase!r}"
                )

    for relative, patterns in FORBIDDEN_WORKFLOW_PATTERNS.items():
        text = loaded.get(relative)
        if text is None:
            path = root / relative
            text = path.read_text(encoding="utf-8") if path.exists() else ""
        for pattern in patterns:
            if pattern.lower() in text.lower():
                errors.append(
                    f"{relative}: forbidden workflow pattern {pattern!r}"
                )

    agents = (
        (root / "AGENTS.md").read_text(encoding="utf-8")
        if (root / "AGENTS.md").exists()
        else ""
    )
    for pattern in FORBIDDEN_ROOT_PATTERNS:
        if pattern.lower() in agents.lower():
            errors.append(f"AGENTS.md: forbidden pattern {pattern!r}")

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
