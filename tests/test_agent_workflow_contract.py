from pathlib import Path

from scripts.verify_agent_workflow_contract import REQUIRED, verify


def _materialize(root: Path) -> None:
    for relative, phrases in REQUIRED.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(phrases), encoding="utf-8")


def test_contract_passes_when_all_required_phrases_exist(tmp_path: Path):
    _materialize(tmp_path)
    assert verify(tmp_path) == []


def test_contract_detects_missing_routing_report_gate(tmp_path: Path):
    _materialize(tmp_path)
    workflow = tmp_path / ".github/workflows/agent_chatops.yml"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            "verify_agent_routing_report.py", "missing_verifier.py"
        ),
        encoding="utf-8",
    )
    errors = verify(tmp_path)
    assert any("verify_agent_routing_report.py" in error for error in errors)


def test_claude_wrapper_must_remain_thin(tmp_path: Path):
    _materialize(tmp_path)
    (tmp_path / "CLAUDE.md").write_text(
        "@AGENTS.md\nIndependent review\n" + "x" * 4000,
        encoding="utf-8",
    )
    assert any("remain thin" in error for error in verify(tmp_path))


def test_short_sha_prefix_gate_is_forbidden(tmp_path: Path):
    _materialize(tmp_path)
    workflow = tmp_path / ".github/workflows/agent_chatops.yml"
    workflow.write_text(
        workflow.read_text(encoding="utf-8")
        + '\n([0-9a-fA-F]{7,40})\ncase "$head" in "$supplied"*',
        encoding="utf-8",
    )
    errors = verify(tmp_path)
    assert any("{7,40}" in error for error in errors)
    assert any('case "$head"' in error for error in errors)


def test_chatops_cannot_checkout_or_call_ai(tmp_path: Path):
    _materialize(tmp_path)
    workflow = tmp_path / ".github/workflows/agent_chatops.yml"
    workflow.write_text(
        workflow.read_text(encoding="utf-8")
        + "\nuses: actions/checkout@v4\nuses: anthropics/claude-code-action@v1",
        encoding="utf-8",
    )
    errors = verify(tmp_path)
    assert any("actions/checkout" in error for error in errors)
    assert any("claude-code-action" in error for error in errors)


def test_repo_ai_inference_workflow_is_forbidden(tmp_path: Path):
    _materialize(tmp_path)
    workflow = tmp_path / ".github/workflows/claude_review.yml"
    workflow.write_text(
        "uses: anthropics/claude-code-action@v1\n"
        "anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}\n",
        encoding="utf-8",
    )
    errors = verify(tmp_path)
    assert any("must not exist" in error for error in errors)
    assert any("ANTHROPIC_API_KEY" in error for error in errors)
