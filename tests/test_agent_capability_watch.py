from pathlib import Path

from scripts import agent_capability_watch as watch


def test_normalize_html_removes_script_and_hash_is_stable():
    a = watch.normalize_html(
        "<main><h1>Title</h1><script>secret()</script><p>Hello</p></main>"
    )
    b = watch.normalize_html("<main> <h1>Title</h1> <p>Hello</p> </main>")
    assert "secret" not in a
    assert watch.sha256(a) == watch.sha256(b)


def test_evaluate_source_requires_human_baseline():
    config = {
        "fetch_validation": {
            "min_normalized_chars": 5,
            "allowed_host_suffixes": ["example.com"],
        }
    }
    result = watch.evaluate_source(
        {
            "id": "official",
            "url": "https://docs.example.com/x",
            "approved_sha256": "",
        },
        watch.Fetched(
            "<main>official current content</main>",
            "https://docs.example.com/x",
            "text/html",
        ),
        config,
    )
    assert result["status"] == "baseline_missing"
    assert len(result["sha256"]) == 64


def test_unexpected_redirect_fails_closed():
    result = watch.evaluate_source(
        {
            "id": "official",
            "url": "https://docs.example.com/x",
            "approved_sha256": "abc",
        },
        watch.Fetched(
            "<main>long enough official content</main>",
            "https://evil.invalid/x",
            "text/html",
        ),
        {
            "fetch_validation": {
                "min_normalized_chars": 5,
                "allowed_host_suffixes": ["example.com"],
            }
        },
    )
    assert result["status"] == "unexpected_redirect"


def _agents_contract() -> str:
    return " ".join(
        [
            "current remote HEAD",
            "quota",
            "authenticated delivery path",
            "agent-routing-report:v1",
            "CHANGES_REQUIRED",
            "BLOCKED_DELIVERY",
            "needs-kevin",
            "not_decision_grade",
            "Kevin",
        ]
    )


def test_offline_report_audits_local_contract(tmp_path: Path):
    required = ["AGENTS.md", "CLAUDE.md"]
    (tmp_path / "AGENTS.md").write_text(_agents_contract(), encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("@AGENTS.md", encoding="utf-8")
    report = watch.build_report(
        {
            "last_verified": "2099-01-01",
            "review_interval_days": 30,
            "required_local_files": required,
            "sources": [],
        },
        offline=True,
        root=tmp_path,
    )
    assert report["overall_status"] == "ok"
    assert report["sources"] == []
    assert report["schema_version"] == 2


def test_missing_local_contract_blocks(tmp_path: Path):
    report = watch.build_report(
        {
            "last_verified": "2099-01-01",
            "review_interval_days": 30,
            "required_local_files": ["AGENTS.md"],
            "sources": [],
        },
        offline=True,
        root=tmp_path,
    )
    assert report["overall_status"] == "blocked"


def test_repo_ai_inference_workflow_blocks_offline_audit(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text(_agents_contract(), encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("@AGENTS.md", encoding="utf-8")
    workflow = tmp_path / ".github/workflows/claude_review.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("uses: anthropics/claude-code-action@v1", encoding="utf-8")
    findings = watch.audit_local(
        {"required_local_files": ["AGENTS.md", "CLAUDE.md"]}, tmp_path
    )
    assert any(
        item["code"] == "repo_ai_inference_workflow_present"
        for item in findings
    )
