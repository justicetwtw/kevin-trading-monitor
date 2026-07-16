#!/usr/bin/env python3
"""Validate a trusted, SHA-bound ``agent-routing-report:v1``.

The report normally lives in a top-level PR comment so its ``head_sha`` can bind
to the already-pushed remote HEAD without creating a self-changing commit loop.
This verifier is deterministic: it performs no model inference and reads no
secrets.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

START = "<!-- agent-routing-report:v1 -->"
END = "<!-- /agent-routing-report:v1 -->"
SCHEMA = "agent-routing-report:v1"
TRUSTED_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}
MODEL_TIERS = {"lower", "peer", "higher", "inherit", "unknown"}
DELEGATION_OUTCOMES = {"completed", "partial", "blocked", "cancelled"}
CI_STATUSES = {"pass", "pending", "failed", "blocked", "unavailable"}
USAGE_STATUSES = {"available", "unavailable"}
FORBIDDEN_KEYS = {
    "chain_of_thought",
    "chain-of-thought",
    "reasoning_trace",
    "hidden_reasoning",
    "secret",
    "secrets",
    "raw_credential",
    "raw_credentials",
    "private_prompt",
    "full_prompt",
    "complete_prompt",
}


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None


def _walk_keys(value: Any) -> list[str]:
    keys: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            keys.append(str(key).lower())
            keys.extend(_walk_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.extend(_walk_keys(item))
    return keys


def extract_report(body: str) -> dict[str, Any] | None:
    """Extract the first routing-report JSON object from one comment body."""
    if START not in body or END not in body:
        return None
    fragment = body.split(START, 1)[1].split(END, 1)[0].strip()
    fence = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", fragment)
    if fence:
        fragment = fence.group(1).strip()
    try:
        parsed = json.loads(fragment)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def validate_report(report: Any, expected_head: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(report, dict):
        return ["report must be a JSON object"]
    if report.get("schema_version") != SCHEMA:
        errors.append(f"schema_version must be {SCHEMA!r}")
    head = report.get("head_sha")
    if not _is_sha(head):
        errors.append("head_sha must be a lowercase 40-character SHA")
    elif head != expected_head:
        errors.append(f"head_sha {head!r} does not equal current remote HEAD {expected_head!r}")

    generated_at = report.get("generated_at")
    if not _nonempty(generated_at):
        errors.append("generated_at is required")
    else:
        try:
            datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
        except ValueError:
            errors.append("generated_at must be ISO-8601")

    owner = report.get("implementation_owner")
    if not isinstance(owner, dict):
        errors.append("implementation_owner must be an object")
    else:
        if owner.get("role") != "implementation_owner":
            errors.append("implementation_owner.role must be 'implementation_owner'")
        for field in ("provider", "surface", "session_mode", "assigned_at"):
            if not _nonempty(owner.get(field)):
                errors.append(f"implementation_owner.{field} is required")
        basis = owner.get("assignment_basis")
        if not isinstance(basis, list) or not basis or not all(_nonempty(item) for item in basis):
            errors.append("implementation_owner.assignment_basis must be a non-empty string list")

    subagents_used = report.get("subagents_used")
    delegations = report.get("delegations")
    if not isinstance(subagents_used, bool):
        errors.append("subagents_used must be boolean")
    if not isinstance(delegations, list):
        errors.append("delegations must be an array")
        delegations = []
    if subagents_used is False:
        if delegations:
            errors.append("delegations must be empty when subagents_used is false")
        if not _nonempty(report.get("subagents_not_used_reason")):
            errors.append("subagents_not_used_reason is required when subagents_used is false")
    elif subagents_used is True and not delegations:
        errors.append("at least one delegation is required when subagents_used is true")

    for index, delegation in enumerate(delegations):
        prefix = f"delegations[{index}]"
        if not isinstance(delegation, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for field in ("purpose", "read_write_ownership"):
            if not _nonempty(delegation.get(field)):
                errors.append(f"{prefix}.{field} is required")
        if delegation.get("relative_model_tier") not in MODEL_TIERS:
            errors.append(f"{prefix}.relative_model_tier is invalid")
        if delegation.get("outcome") not in DELEGATION_OUTCOMES:
            errors.append(f"{prefix}.outcome is invalid")
        evidence = delegation.get("deterministic_evidence")
        if not isinstance(evidence, list) or not all(_nonempty(item) for item in evidence):
            errors.append(f"{prefix}.deterministic_evidence must be a string list")

    fallback = report.get("escalation_or_fallback")
    if not isinstance(fallback, dict) or not isinstance(fallback.get("occurred"), bool):
        errors.append("escalation_or_fallback.occurred must be boolean")
    elif fallback.get("occurred") and not _nonempty(fallback.get("reason")):
        errors.append("escalation_or_fallback.reason is required when occurred is true")

    usage = report.get("usage_evidence")
    if not isinstance(usage, dict):
        errors.append("usage_evidence must be an object")
    else:
        status = usage.get("status")
        if status not in USAGE_STATUSES:
            errors.append("usage_evidence.status must be available or unavailable")
        if not _nonempty(usage.get("source")):
            errors.append("usage_evidence.source is required")
        metrics = usage.get("metrics")
        if not isinstance(metrics, dict):
            errors.append("usage_evidence.metrics must be an object")
        elif status == "unavailable" and metrics:
            errors.append("usage_evidence.metrics must be empty when status is unavailable")
        elif status == "available" and not metrics:
            errors.append("usage_evidence.metrics must be non-empty when status is available")

    reverification = report.get("lead_reverification")
    if not isinstance(reverification, dict):
        errors.append("lead_reverification must be an object")
    else:
        if not isinstance(reverification.get("performed"), bool):
            errors.append("lead_reverification.performed must be boolean")
        if not _nonempty(reverification.get("summary")):
            errors.append("lead_reverification.summary is required")
        if subagents_used and reverification.get("performed") is not True:
            errors.append("lead_reverification.performed must be true when subagents were used")

    tests = report.get("tests")
    if not isinstance(tests, list) or not tests:
        errors.append("tests must be a non-empty array")
    else:
        for index, item in enumerate(tests):
            if not isinstance(item, dict):
                errors.append(f"tests[{index}] must be an object")
                continue
            if not _nonempty(item.get("name")) or item.get("status") not in {"pass", "fail", "skipped"}:
                errors.append(f"tests[{index}] requires name and valid status")
            if not _nonempty(item.get("evidence")):
                errors.append(f"tests[{index}].evidence is required")

    ci = report.get("ci")
    if not isinstance(ci, dict):
        errors.append("ci must be an object")
    else:
        if ci.get("status") not in CI_STATUSES:
            errors.append("ci.status is invalid")
        if ci.get("status") != "pass":
            errors.append("ci.status must be pass before /agent-fix-complete")
        if not _nonempty(ci.get("source")) or not _nonempty(ci.get("evidence")):
            errors.append("ci.source and ci.evidence are required")

    reviewer = report.get("independent_reviewer")
    if reviewer is not None:
        if not isinstance(reviewer, dict):
            errors.append("independent_reviewer must be an object when supplied")
        else:
            if reviewer.get("same_as_owner") is not False:
                errors.append("independent_reviewer.same_as_owner must be false")
            for field in ("provider", "surface", "status"):
                if not _nonempty(reviewer.get(field)):
                    errors.append(f"independent_reviewer.{field} is required")

    forbidden = sorted(set(_walk_keys(report)) & FORBIDDEN_KEYS)
    if forbidden:
        errors.append("forbidden sensitive/reasoning keys present: " + ", ".join(forbidden))
    return errors


def find_valid_trusted_report(comments: Any, expected_head: str) -> tuple[dict[str, Any] | None, list[str]]:
    """Return the newest schema-valid report posted by a trusted human actor."""
    if not isinstance(comments, list):
        return None, ["comments payload must be an array"]
    diagnostics: list[str] = []
    for comment in reversed(comments):
        if not isinstance(comment, dict):
            continue
        body = str(comment.get("body") or "")
        if START not in body:
            continue
        association = str(comment.get("author_association") or "").upper()
        user_type = str((comment.get("user") or {}).get("type") or "")
        login = str((comment.get("user") or {}).get("login") or "unknown")
        if association not in TRUSTED_ASSOCIATIONS or user_type == "Bot":
            diagnostics.append(f"ignored untrusted routing report from {login}")
            continue
        report = extract_report(body)
        if report is None:
            diagnostics.append(f"invalid JSON routing report from {login}")
            continue
        errors = validate_report(report, expected_head)
        if not errors:
            return report, diagnostics
        diagnostics.append(f"routing report from {login} invalid: " + "; ".join(errors))
    return None, diagnostics or ["no agent-routing-report:v1 comment found"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-head", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--report-file")
    source.add_argument("--comments-json")
    args = parser.parse_args(argv)

    expected = args.expected_head.lower()
    if not _is_sha(expected):
        print("expected HEAD must be a lowercase 40-character SHA", file=sys.stderr)
        return 2

    if args.report_file:
        report = json.loads(Path(args.report_file).read_text(encoding="utf-8"))
        errors = validate_report(report, expected)
        if errors:
            for error in errors:
                print(f"- {error}", file=sys.stderr)
            return 1
    else:
        comments = json.loads(Path(args.comments_json).read_text(encoding="utf-8"))
        report, diagnostics = find_valid_trusted_report(comments, expected)
        if report is None:
            for item in diagnostics:
                print(f"- {item}", file=sys.stderr)
            return 1

    print(f"agent-routing-report:v1 valid for HEAD {expected}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
