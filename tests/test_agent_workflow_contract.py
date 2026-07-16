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


def test_contract_detects_missing_sha_gate(tmp_path: Path):
    _materialize(tmp_path)
    workflow = tmp_path / ".github/workflows/claude_review.yml"
    workflow.write_text("anthropics/claude-code-action@v1\nANTHROPIC_API_KEY\nauthor_association\nReview only", encoding="utf-8")
    errors = verify(tmp_path)
    assert any("40-character" in error for error in errors)


def test_claude_wrapper_must_remain_thin(tmp_path: Path):
    _materialize(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("@AGENTS.md\nIndependent review\n" + "x" * 4000, encoding="utf-8")
    assert any("remain thin" in error for error in verify(tmp_path))
