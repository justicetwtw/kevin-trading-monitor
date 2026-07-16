import json

from scripts.verify_agent_routing_report import (
    END,
    START,
    extract_report,
    find_valid_trusted_report,
    validate_report,
)


HEAD = "a" * 40


def _report(**overrides):
    value = {
        "schema_version": "agent-routing-report:v1",
        "head_sha": HEAD,
        "generated_at": "2026-07-16T18:00:00+08:00",
        "implementation_owner": {
            "role": "implementation_owner",
            "provider": "openai",
            "surface": "chatgpt",
            "session_mode": "conversation_orchestrator_direct",
            "assigned_at": "2026-07-16T17:00:00+08:00",
            "assignment_basis": [
                "authenticated delivery path available",
                "task fit and remaining quota were adequate",
            ],
        },
        "subagents_used": False,
        "subagents_not_used_reason": "The work was sequential and shared-file heavy.",
        "delegations": [],
        "escalation_or_fallback": {"occurred": False, "reason": "none"},
        "usage_evidence": {
            "status": "unavailable",
            "source": "The current product surface exposes no per-task token/credit/latency export.",
            "metrics": {},
        },
        "lead_reverification": {
            "performed": True,
            "summary": "Reviewed the final diff and matched it to deterministic tests.",
        },
        "tests": [
            {
                "name": "pytest",
                "status": "pass",
                "evidence": "GitHub Actions CI run 123",
            }
        ],
        "ci": {
            "status": "pass",
            "source": "GitHub Actions",
            "evidence": "CI run 123 at exact HEAD",
        },
        "independent_reviewer": {
            "provider": "anthropic",
            "surface": "authenticated_fable_task",
            "status": "pending",
            "same_as_owner": False,
        },
    }
    value.update(overrides)
    return value


def _comment(report, *, association="OWNER", user_type="User"):
    body = f"{START}\n```json\n{json.dumps(report)}\n```\n{END}"
    return {
        "body": body,
        "author_association": association,
        "user": {"login": "kevin", "type": user_type},
    }


def test_valid_report_passes():
    assert validate_report(_report(), HEAD) == []


def test_report_must_bind_exact_current_head():
    errors = validate_report(_report(head_sha="b" * 40), HEAD)
    assert any("current remote HEAD" in error for error in errors)


def test_no_subagents_requires_reason_and_empty_delegations():
    report = _report(subagents_not_used_reason="")
    errors = validate_report(report, HEAD)
    assert "subagents_not_used_reason is required when subagents_used is false" in errors


def test_subagent_delegation_requires_reverification_and_evidence():
    report = _report(
        subagents_used=True,
        subagents_not_used_reason=None,
        delegations=[
            {
                "purpose": "Read-only source audit",
                "read_write_ownership": "read-only; no branch writes",
                "relative_model_tier": "lower",
                "outcome": "completed",
                "deterministic_evidence": ["source table checked"],
            }
        ],
        lead_reverification={"performed": False, "summary": "not checked"},
    )
    errors = validate_report(report, HEAD)
    assert any("must be true when subagents were used" in error for error in errors)


def test_unavailable_usage_cannot_contain_invented_metrics():
    report = _report(
        usage_evidence={
            "status": "unavailable",
            "source": "no product export",
            "metrics": {"tokens": 12345},
        }
    )
    assert any("must be empty" in error for error in validate_report(report, HEAD))


def test_forbidden_reasoning_or_secret_keys_fail():
    report = _report()
    report["chain_of_thought"] = "hidden"
    errors = validate_report(report, HEAD)
    assert any("forbidden" in error for error in errors)


def test_extracts_fenced_json():
    report = _report()
    body = f"prefix\n{START}\n```json\n{json.dumps(report)}\n```\n{END}\nsuffix"
    assert extract_report(body) == report


def test_newest_trusted_valid_comment_wins():
    comments = [
        _comment(_report(head_sha="b" * 40)),
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
    report = _report(ci={"status": "pending", "source": "GitHub Actions", "evidence": "run 1"})
    assert "ci.status must be pass before /agent-fix-complete" in validate_report(report, HEAD)
