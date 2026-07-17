#!/usr/bin/env python3
"""Validate a trusted, SHA-bound ``agent-routing-report:v1``.

The schema intentionally matches the current canonical workflow in
``jin-yi-yang-bot``. This verifier is deterministic: it performs no model
inference, reads no secret and treats the routing report as process/cost evidence
that supplements — never replaces — code, tests, CI and remote HEAD.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA = "agent-routing-report:v1"
MAX_REPORT_BYTES = 16_384
TRUSTED_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}
MODEL_TIERS = {"lower", "peer", "higher", "inherit", "unknown"}
DELEGATION_OWNERSHIP = {"read_only", "write_reintegrated_by_owner"}
TEST_RESULTS = {"pass", "fail", "not_run"}
CI_STATUSES = {"pass", "pending", "fail", "not_applicable"}
USAGE_STATUSES = {"reported", "unavailable"}
# The only reviewer statuses that prove an independent review PASSED.
# pending / in_review / blocked_delivery are progress notes, not verdicts.
REVIEWER_PASS_STATUSES = {"pass"}
HEAD_PATTERN = re.compile(r"^[0-9a-f]{40}$")
MARKER_PATTERN = re.compile(
    r"<!--\s*agent-routing-report:v1\s+head=([0-9a-fA-F]{40})\s*-->"
)
# A review PASS must exist as its own explicit, HEAD-bound artifact posted
# separately from the routing report, so the owner's report cannot simply
# self-attest a reviewer verdict. In a single-maintainer repo this cannot
# cryptographically prove reviewer independence; Kevin's merge gate remains
# the final backstop, and this marker makes the verdict auditable.
VERDICT_MARKER_PATTERN = re.compile(
    r"<!--\s*agent-review-verdict:v1\s+head=([0-9a-fA-F]{40})\s+verdict=([A-Za-z_]+)\s*-->"
)
FORBIDDEN_KEY_PATTERNS = (
    ("forbidden_chain_of_thought_key", re.compile(r"chain[_-]?of[_-]?thought|reasoning[_-]?trace|^cot$", re.I)),
    ("forbidden_prompt_dump_key", re.compile(r"(?:system|full|raw|private)[_-]?prompt", re.I)),
    ("forbidden_credential_key", re.compile(r"api[_-]?key|credential|password|(?:^|[_-])secret(?:$|[_-])", re.I)),
)
SECRET_VALUE_PATTERNS = (
    ("openai_style_key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._-]{24,}\b")),
)


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and HEAD_PATTERN.fullmatch(value) is not None


def _scan_forbidden(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            for code, pattern in FORBIDDEN_KEY_PATTERNS:
                if pattern.search(key_text):
                    errors.append(f"{code} at {path}.{key_text}")
            _scan_forbidden(child, f"{path}.{key_text}", errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_forbidden(child, f"{path}[{index}]", errors)
    elif isinstance(value, str):
        for code, pattern in SECRET_VALUE_PATTERNS:
            if pattern.search(value):
                errors.append(f"secret_like_value_{code} at {path}")


def extract_report(body: str) -> tuple[str, dict[str, Any] | None, str | None] | None:
    """Return marker head, report and parse error from one PR comment."""
    if not isinstance(body, str):
        return None
    marker = MARKER_PATTERN.search(body)
    if marker is None:
        return None
    marker_head = marker.group(1).lower()
    fence = re.search(r"```json\s*\n([\s\S]*?)\n```", body)
    if fence is None:
        return marker_head, None, "missing_json_fence"
    try:
        parsed = json.loads(fence.group(1))
    except json.JSONDecodeError:
        return marker_head, None, "invalid_json"
    if not isinstance(parsed, dict):
        return marker_head, None, "report_not_object"
    return marker_head, parsed, None


def validate_report(
    report: Any,
    expected_head: str,
    *,
    require_reviewer_pass: bool = False,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(report, dict):
        return ["report must be a JSON object"]

    serialized = json.dumps(report, ensure_ascii=False, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > MAX_REPORT_BYTES:
        errors.append(f"report exceeds {MAX_REPORT_BYTES} bytes")

    if report.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA!r}")
    head = report.get("head")
    if not _is_sha(head):
        errors.append("head must be a lowercase 40-character SHA")
    elif head != expected_head:
        errors.append(
            f"head {head!r} does not equal current remote HEAD {expected_head!r}"
        )

    generated_at = report.get("generated_at")
    if not _nonempty(generated_at):
        errors.append("generated_at is required")
    else:
        try:
            datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
        except ValueError:
            errors.append("generated_at must be ISO-8601")

    owner = report.get("owner")
    if not isinstance(owner, dict):
        errors.append("owner must be an object")
    else:
        if owner.get("role") != "implementation_owner":
            errors.append("owner.role must be 'implementation_owner'")
        # surface and assignment_basis are the authenticated-delivery-path
        # and quota/task-fit evidence; the canonical report requires both.
        for field in ("provider", "session_mode", "surface"):
            if not _nonempty(owner.get(field)):
                errors.append(f"owner.{field} is required")
        basis = owner.get("assignment_basis")
        if (
            not isinstance(basis, list)
            or not basis
            or not all(_nonempty(item) for item in basis)
        ):
            errors.append("owner.assignment_basis must be a non-empty string list")

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
        if not _nonempty(report.get("no_delegation_reason")):
            errors.append(
                "no_delegation_reason is required when subagents_used is false"
            )
    elif subagents_used is True and not delegations:
        errors.append("at least one delegation is required when subagents_used is true")

    for index, delegation in enumerate(delegations):
        prefix = f"delegations[{index}]"
        if not isinstance(delegation, dict):
            errors.append(f"{prefix} must be an object")
            continue
        if not _nonempty(delegation.get("purpose")):
            errors.append(f"{prefix}.purpose is required")
        if delegation.get("ownership") not in DELEGATION_OWNERSHIP:
            errors.append(f"{prefix}.ownership is invalid")
        if delegation.get("model_tier") not in MODEL_TIERS:
            errors.append(f"{prefix}.model_tier is invalid")
        if not _nonempty(delegation.get("outcome")):
            errors.append(f"{prefix}.outcome is required")
        if not _nonempty(delegation.get("evidence")):
            errors.append(f"{prefix}.evidence is required")

    fallback = report.get("escalation_or_fallback")
    if not isinstance(fallback, dict) or not isinstance(
        fallback.get("occurred"), bool
    ):
        errors.append("escalation_or_fallback.occurred must be boolean")
    elif fallback.get("occurred") and not _nonempty(fallback.get("reason")):
        errors.append(
            "escalation_or_fallback.reason is required when occurred is true"
        )

    usage = report.get("usage_metrics")
    if not isinstance(usage, dict) or usage.get("status") not in USAGE_STATUSES:
        errors.append("usage_metrics.status must be reported or unavailable")
    else:
        status = usage.get("status")
        if not _nonempty(usage.get("source")):
            errors.append("usage_metrics.source is required")
        metrics_present = "metrics" in usage
        metrics = usage.get("metrics")
        if status == "reported" and (
            not isinstance(metrics, dict) or not metrics
        ):
            errors.append(
                "usage_metrics.metrics must be non-empty when status is reported"
            )
        if status == "unavailable" and metrics_present:
            errors.append(
                "usage_metrics.metrics must be omitted when status is unavailable"
            )

    reverification = report.get("lead_reverification")
    if not isinstance(reverification, dict):
        errors.append("lead_reverification must be an object")
    else:
        if not isinstance(reverification.get("performed"), bool):
            errors.append("lead_reverification.performed must be boolean")
        if not _nonempty(reverification.get("notes")):
            errors.append("lead_reverification.notes is required")
        if subagents_used and reverification.get("performed") is not True:
            errors.append(
                "lead_reverification.performed must be true when subagents were used"
            )

    tests = report.get("tests")
    if not isinstance(tests, list) or not tests:
        errors.append("tests must be a non-empty array")
    else:
        for index, item in enumerate(tests):
            prefix = f"tests[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{prefix} must be an object")
                continue
            if not _nonempty(item.get("command")):
                errors.append(f"{prefix}.command is required")
            if item.get("result") not in TEST_RESULTS:
                errors.append(f"{prefix}.result is invalid")

    ci = report.get("ci")
    if not isinstance(ci, dict) or ci.get("status") not in CI_STATUSES:
        errors.append("ci.status is invalid")
    elif ci.get("status") != "pass":
        errors.append("ci.status must be pass before /agent-fix-complete")

    reviewer = report.get("independent_reviewer")
    if require_reviewer_pass and reviewer is None:
        errors.append(
            "independent_reviewer is required for /agent-review-pass"
        )
    if reviewer is not None:
        if not isinstance(reviewer, dict):
            errors.append("independent_reviewer must be an object when supplied")
        else:
            if reviewer.get("same_as_owner") is not False:
                errors.append("independent_reviewer.same_as_owner must be false")
            for field in ("provider", "surface", "status"):
                if not _nonempty(reviewer.get(field)):
                    errors.append(f"independent_reviewer.{field} is required")
            if require_reviewer_pass:
                status = str(reviewer.get("status") or "").lower()
                if status not in REVIEWER_PASS_STATUSES:
                    errors.append(
                        "independent_reviewer.status must be an explicit PASS "
                        f"verdict for /agent-review-pass; got {status!r} "
                        "(pending/in_review/blocked statuses are not proof)"
                    )

    _scan_forbidden(report, "$", errors)
    return errors


def validate_report_comment(
    body: str,
    expected_head: str,
    *,
    require_reviewer_pass: bool = False,
) -> list[str]:
    extracted = extract_report(body)
    if extracted is None:
        return ["missing agent-routing-report:v1 head=<sha> marker"]
    marker_head, report, parse_error = extracted
    if parse_error:
        return [parse_error]
    assert report is not None
    errors = validate_report(
        report, expected_head, require_reviewer_pass=require_reviewer_pass
    )
    if report.get("head") != marker_head:
        errors.append(
            f"marker head {marker_head!r} does not equal report head {report.get('head')!r}"
        )
    return errors


def _is_trusted_comment(comment: dict[str, Any]) -> bool:
    association = str(comment.get("author_association") or "").upper()
    user = comment.get("user") or {}
    user_type = str(user.get("type") or "")
    return association in TRUSTED_ASSOCIATIONS and user_type != "Bot"


def find_review_pass_verdict(
    comments: list[Any],
    expected_head: str,
    *,
    exclude_index: int | None = None,
) -> bool:
    """Return whether a distinct trusted comment carries a HEAD-bound PASS."""
    for index, comment in enumerate(comments):
        if index == exclude_index or not isinstance(comment, dict):
            continue
        if not _is_trusted_comment(comment):
            continue
        marker = VERDICT_MARKER_PATTERN.search(str(comment.get("body") or ""))
        if marker is None:
            continue
        if marker.group(1).lower() != expected_head:
            continue
        if marker.group(2).lower() in REVIEWER_PASS_STATUSES:
            return True
    return False


def find_valid_trusted_report(
    comments: Any,
    expected_head: str,
    *,
    require_reviewer_pass: bool = False,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Return newest schema-valid report posted by a trusted human actor."""
    if not isinstance(comments, list):
        return None, ["comments payload must be an array"]
    diagnostics: list[str] = []
    for index in range(len(comments) - 1, -1, -1):
        comment = comments[index]
        if not isinstance(comment, dict):
            continue
        body = str(comment.get("body") or "")
        if "agent-routing-report:v1" not in body:
            continue
        user = comment.get("user") or {}
        login = str(user.get("login") or "unknown")
        if not _is_trusted_comment(comment):
            diagnostics.append(f"ignored untrusted routing report from {login}")
            continue
        errors = validate_report_comment(
            body, expected_head, require_reviewer_pass=require_reviewer_pass
        )
        if not errors:
            if require_reviewer_pass and not find_review_pass_verdict(
                comments, expected_head, exclude_index=index
            ):
                # The report's own reviewer field is self-attested; the PASS
                # must also exist as a separate HEAD-bound verdict comment.
                diagnostics.append(
                    "no distinct trusted agent-review-verdict:v1 PASS comment "
                    f"bound to current HEAD {expected_head}"
                )
                return None, diagnostics
            extracted = extract_report(body)
            assert extracted is not None and extracted[1] is not None
            return extracted[1], diagnostics
        diagnostics.append(
            f"routing report from {login} invalid: " + "; ".join(errors)
        )
    return None, diagnostics or ["no agent-routing-report:v1 comment found"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-head", required=True)
    parser.add_argument(
        "--require-reviewer-pass",
        action="store_true",
        help=(
            "Require an explicit independent-reviewer PASS verdict bound to "
            "the expected HEAD (used by /agent-review-pass)."
        ),
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--report-file")
    source.add_argument("--comment-file")
    source.add_argument("--comments-json")
    args = parser.parse_args(argv)

    expected = args.expected_head.lower()
    if not _is_sha(expected):
        print("expected HEAD must be a lowercase 40-character SHA", file=sys.stderr)
        return 2

    if args.report_file:
        report = json.loads(Path(args.report_file).read_text(encoding="utf-8"))
        errors = validate_report(
            report, expected, require_reviewer_pass=args.require_reviewer_pass
        )
    elif args.comment_file:
        errors = validate_report_comment(
            Path(args.comment_file).read_text(encoding="utf-8"),
            expected,
            require_reviewer_pass=args.require_reviewer_pass,
        )
    else:
        comments = json.loads(Path(args.comments_json).read_text(encoding="utf-8"))
        report, diagnostics = find_valid_trusted_report(
            comments,
            expected,
            require_reviewer_pass=args.require_reviewer_pass,
        )
        errors = [] if report is not None else diagnostics

    if errors:
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"agent-routing-report:v1 valid for HEAD {expected}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
