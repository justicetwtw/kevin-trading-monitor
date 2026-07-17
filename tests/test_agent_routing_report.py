import json

from scripts.verify_agent_routing_report import (
    MAX_REPORT_BYTES,
    extract_report,
    find_review_pass_verdict,
    find_valid_trusted_report,
    validate_report,
    validate_report_comment,
)


HEAD = "a" * 40


def _report(**overrides):
    value = {
        "schema": "agent-routing-report:v1",
        "head": HEAD,
        "generated_at": "2026-07-16T18:00:00+08:00",
        "owner": {
            "role": "implementation_owner",
            "provider": "openai",
            "surface": "chatgpt-connected-github",
            "session_mode": "conversation_orchestrator_direct",
            "assignment_basis": [
                "authenticated delivery path available",
                "task fit and remaining quota were adequate",
            ],
        },
        "subagents_used": False,
        "no_delegation_reason": "The work was sequential and shared-file heavy.",
        "delegations": [],
        "escalation_or_fallback": {"occurred": False, "reason": "none"},
        "usage_metrics": {
            "status": "unavailable",
            "source": "The current product surface exposes no per-task token/credit/latency export.",
        },
        "lead_reverification": {
            "performed": True,
            "notes": "Reviewed the final diff and matched it to deterministic tests.",
        },
        "tests": [
            {"command": "python -m pytest -q", "result": "pass"}
        ],
        "ci": {"status": "pass", "source": "GitHub Actions run 123"},
        "independent_reviewer": {
            "provider": "anthropic",
            "surface": "authenticated_fable_task",
            "status": "pending",
            "same_as_owner": False,
        },
    }
    value.update(overrides)
    return value


def _body(report, marker_head=HEAD):
    return (
        f"<!-- agent-routing-report:v1 head={marker_head} -->\n"
        f"```json\n{json.dumps(report)}\n```"
    )


def _comment(report, *, association="OWNER", user_type="User"):
    return {
        "body": _body(report),
        "author_association": association,
        "user": {"login": "kevin", "type": user_type},
    }


def test_valid_report_passes():
    assert validate_report(_report(), HEAD) == []
    assert validate_report_comment(_body(_report()), HEAD) == []


def test_report_must_bind_exact_current_head_and_marker():
    errors = validate_report(_report(head="b" * 40), HEAD)
    assert any("current remote HEAD" in error for error in errors)
    marker_errors = validate_report_comment(_body(_report(), marker_head="b" * 40), HEAD)
    assert any("marker head" in error for error in marker_errors)


def test_no_subagents_requires_reason_and_empty_delegations():
    report = _report(no_delegation_reason="")
    assert (
        "no_delegation_reason is required when subagents_used is false"
        in validate_report(report, HEAD)
    )


def test_subagent_delegation_requires_reverification_and_evidence():
    report = _report(
        subagents_used=True,
        no_delegation_reason=None,
        delegations=[
            {
                "purpose": "Read-only source audit",
                "ownership": "read_only",
                "model_tier": "lower",
                "outcome": "completed",
                "evidence": "source table checked",
            }
        ],
        lead_reverification={"performed": False, "notes": "not checked"},
    )
    errors = validate_report(report, HEAD)
    assert any("must be true when subagents were used" in error for error in errors)


def test_delegation_write_ownership_cannot_fork():
    report = _report(
        subagents_used=True,
        no_delegation_reason=None,
        delegations=[
            {
                "purpose": "Parallel implementation",
                "ownership": "parallel_branch_owner",
                "model_tier": "peer",
                "outcome": "completed",
                "evidence": "none",
            }
        ],
    )
    assert any("ownership is invalid" in error for error in validate_report(report, HEAD))


def test_unavailable_usage_must_omit_metrics():
    report = _report(
        usage_metrics={
            "status": "unavailable",
            "source": "no product export",
            "metrics": {"tokens": 12345},
        }
    )
    assert any("must be omitted" in error for error in validate_report(report, HEAD))


def test_forbidden_reasoning_secret_keys_and_values_fail():
    report = _report()
    report["chain_of_thought"] = "hidden"
    report["notes"] = "Bearer abcdefghijklmnopqrstuvwxyz123456"
    errors = validate_report(report, HEAD)
    assert any("forbidden_chain_of_thought_key" in error for error in errors)
    assert any("secret_like_value_bearer_token" in error for error in errors)


def test_report_size_is_bounded():
    report = _report()
    report["notes"] = "x" * MAX_REPORT_BYTES
    assert any("exceeds" in error for error in validate_report(report, HEAD))


def test_extracts_marker_and_fenced_json():
    report = _report()
    marker_head, parsed, error = extract_report(_body(report))
    assert marker_head == HEAD
    assert parsed == report
    assert error is None


def test_newest_trusted_valid_comment_wins():
    comments = [
        _comment(_report(head="b" * 40)),
        _comment(_report()),
    ]
    report, diagnostics = find_valid_trusted_report(comments, HEAD)
    assert report == _report()
    assert diagnostics == []


def test_bot_or_untrusted_comment_is_not_evidence():
    comments = [
        _comment(_report(), association="NONE"),
        _comment(_report(), user_type="Bot"),
    ]
    report, diagnostics = find_valid_trusted_report(comments, HEAD)
    assert report is None
    assert all("ignored untrusted" in item for item in diagnostics)


def test_fix_complete_requires_passing_ci_in_report():
    report = _report(ci={"status": "pending", "source": "GitHub Actions"})
    assert "ci.status must be pass before /agent-fix-complete" in validate_report(
        report, HEAD
    )


def test_reviewer_must_not_be_owner():
    report = _report(
        independent_reviewer={
            "provider": "openai",
            "surface": "same_session",
            "status": "pending",
            "same_as_owner": True,
        }
    )
    assert any("same_as_owner must be false" in error for error in validate_report(report, HEAD))


def test_owner_surface_and_assignment_basis_are_required():
    """R20: delivery-path and quota/task-fit evidence cannot be omitted."""
    no_surface = _report()
    del no_surface["owner"]["surface"]
    assert any(
        "owner.surface" in error
        for error in validate_report(no_surface, HEAD)
    )

    no_basis = _report()
    del no_basis["owner"]["assignment_basis"]
    assert any(
        "assignment_basis" in error
        for error in validate_report(no_basis, HEAD)
    )

    empty_basis = _report()
    empty_basis["owner"]["assignment_basis"] = []
    assert any(
        "assignment_basis" in error
        for error in validate_report(empty_basis, HEAD)
    )


def test_review_pass_mode_requires_explicit_reviewer_pass():
    """R21: pending/in_review/blocked statuses never prove a review passed."""
    for status in ("pending", "in_review", "blocked_delivery"):
        report = _report()
        report["independent_reviewer"]["status"] = status
        # The base gate (fix-complete) accepts progress statuses...
        assert validate_report(report, HEAD) == []
        # ...but review-pass mode must reject them.
        errors = validate_report(report, HEAD, require_reviewer_pass=True)
        assert any("PASS" in error for error in errors)

    passed = _report()
    passed["independent_reviewer"]["status"] = "pass"
    assert validate_report(passed, HEAD, require_reviewer_pass=True) == []


def test_review_pass_mode_requires_reviewer_to_exist():
    report = _report()
    del report["independent_reviewer"]
    assert validate_report(report, HEAD) == []
    errors = validate_report(report, HEAD, require_reviewer_pass=True)
    assert any("independent_reviewer is required" in error for error in errors)


def _verdict_comment(head=HEAD, verdict="pass", *, association="OWNER", user_type="User"):
    return {
        "body": (
            "## Independent review verdict\n\n"
            f"<!-- agent-review-verdict:v1 head={head} verdict={verdict} -->"
        ),
        "author_association": association,
        "user": {"login": "kevin", "type": user_type},
    }


def test_review_pass_mode_flows_through_comment_search():
    pending = _comment(_report())
    assert find_valid_trusted_report([pending], HEAD)[0] is not None
    report, diagnostics = find_valid_trusted_report(
        [pending], HEAD, require_reviewer_pass=True
    )
    assert report is None
    assert diagnostics

    passed_report = _report()
    passed_report["independent_reviewer"]["status"] = "pass"
    found, _ = find_valid_trusted_report(
        [_comment(passed_report), _verdict_comment()],
        HEAD,
        require_reviewer_pass=True,
    )
    assert found is not None


def test_review_pass_requires_distinct_head_bound_verdict_comment():
    """C2: a self-attested reviewer field is not proof; a separate trusted
    HEAD-bound agent-review-verdict:v1 PASS comment is required."""
    passed_report = _report()
    passed_report["independent_reviewer"]["status"] = "pass"
    report_comment = _comment(passed_report)

    # Report alone (even claiming pass) is rejected in review-pass mode.
    found, diagnostics = find_valid_trusted_report(
        [report_comment], HEAD, require_reviewer_pass=True
    )
    assert found is None
    assert any("agent-review-verdict:v1" in item for item in diagnostics)

    # A verdict embedded in the SAME comment as the report does not count.
    combined = dict(report_comment)
    combined["body"] += (
        f"\n<!-- agent-review-verdict:v1 head={HEAD} verdict=pass -->"
    )
    found, _ = find_valid_trusted_report(
        [combined], HEAD, require_reviewer_pass=True
    )
    assert found is None

    # Wrong head, non-pass verdict, or untrusted author never satisfy it.
    assert not find_review_pass_verdict([_verdict_comment(head="b" * 40)], HEAD)
    assert not find_review_pass_verdict(
        [_verdict_comment(verdict="changes_required")], HEAD
    )
    assert not find_review_pass_verdict(
        [_verdict_comment(user_type="Bot")], HEAD
    )
    assert not find_review_pass_verdict(
        [_verdict_comment(association="NONE")], HEAD
    )

    # A distinct trusted PASS verdict bound to the exact HEAD satisfies it.
    found, _ = find_valid_trusted_report(
        [report_comment, _verdict_comment()], HEAD, require_reviewer_pass=True
    )
    assert found is not None
