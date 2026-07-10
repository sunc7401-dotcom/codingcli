from __future__ import annotations

import builtins
from pathlib import Path

import pytest

from suncli_py.refactor_agent.commands import RefactorAgentError, run_apply
from suncli_py.refactor_agent.llm_assistant import RefactorLlmAssistant
from suncli_py.refactor_agent.models import (
    CoverageAssessment,
    Evidence,
    JavaContext,
    RefactoringType,
    RefactorIssue,
    RefactorPlan,
    RiskLevel,
    Severity,
    SmellType,
)
from suncli_py.refactor_agent.storage import RefactorAgentStorage


def test_apply_decline_does_not_write_files_or_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = _write_java_file(tmp_path)
    original = source_path.read_text(encoding="utf-8")
    _save_plan(tmp_path, _dead_code_issue(source_path), files_to_modify=["src/main/java/demo/OrderService.java"])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(builtins, "input", lambda _: "n")

    exit_code = run_apply(issue_id="RA-0001")

    assert exit_code == 1
    assert source_path.read_text(encoding="utf-8") == original
    task_dir = next((tmp_path / ".paicli" / "refactor-agent" / "tasks").iterdir())
    assert not (task_dir / "snapshot.json").exists()
    assert not (task_dir / "patch.diff").exists()


def test_apply_uses_llm_edit_plan_and_writes_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_path = _write_java_file(tmp_path)
    issue = _dead_code_issue(source_path)
    _save_plan(tmp_path, issue, files_to_modify=["src/main/java/demo/OrderService.java"])
    monkeypatch.chdir(tmp_path)

    exit_code = run_apply(issue_id="RA-0001", assume_yes=True, llm_assistant=_FakePatchAssistant(issue))

    assert exit_code == 0
    updated = source_path.read_text(encoding="utf-8")
    assert "unusedPrivate" not in updated
    assert "createOrder" in updated

    output = capsys.readouterr().out
    assert "apply" in output
    assert "Diff:" in output
    assert "-    private void unusedPrivate()" in output

    task_dir = next((tmp_path / ".paicli" / "refactor-agent" / "tasks").iterdir())
    assert (task_dir / "snapshot.json").is_file()
    assert (task_dir / "patch.diff").is_file()
    assert (task_dir / "diff_summary.txt").is_file()
    assert (task_dir / "before" / "src" / "main" / "java" / "demo" / "OrderService.java").is_file()


def test_apply_rejects_llm_patch_outside_plan_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = _write_java_file(tmp_path)
    issue = _dead_code_issue(source_path)
    _save_plan(tmp_path, issue, files_to_modify=["src/main/java/demo/Other.java"])
    monkeypatch.chdir(tmp_path)

    with pytest.raises(RefactorAgentError, match="outside plan"):
        run_apply(issue_id="RA-0001", assume_yes=True, llm_assistant=_FakePatchAssistant(issue))

    assert "unusedPrivate" in source_path.read_text(encoding="utf-8")


def test_apply_requires_llm_edit_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = _write_java_file(tmp_path)
    issue = _dead_code_issue(source_path)
    _save_plan(tmp_path, issue, files_to_modify=["src/main/java/demo/OrderService.java"])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(RefactorLlmAssistant, "from_config", classmethod(lambda cls: None))

    with pytest.raises(RefactorAgentError, match="LLM assistant is required"):
        run_apply(issue_id="RA-0001", assume_yes=True, llm_assistant=None)


def _write_java_file(root: Path) -> Path:
    (root / ".git").mkdir()
    source_dir = root / "src" / "main" / "java" / "demo"
    source_dir.mkdir(parents=True)
    source_path = source_dir / "OrderService.java"
    source_path.write_text(
        """
package demo;

public class OrderService {
    private void unusedPrivate() {
        System.out.println("unused");
    }

    public int createOrder(int input) {
        return input + 1;
    }
}
""".lstrip(),
        encoding="utf-8",
    )
    return source_path


def _dead_code_issue(source_path: Path) -> RefactorIssue:
    lines = source_path.read_text(encoding="utf-8").splitlines()
    start_line = next(index for index, line in enumerate(lines, start=1) if "unusedPrivate" in line)
    return RefactorIssue(
        id="RA-0001",
        type=SmellType.DEAD_CODE,
        severity=Severity.LOW,
        file_path="src/main/java/demo/OrderService.java",
        symbol="unusedPrivate",
        start_line=start_line,
        end_line=start_line + 2,
        evidence=[Evidence("private method has no references", {"identifier_occurrences": 1})],
        impact="dead private code adds noise",
        recommendation="remove dead code",
        suggested_refactoring=RefactoringType.REMOVE_DEAD_CODE,
        auto_applicable=True,
        risk_level=RiskLevel.LOW,
        requires_review=False,
    )


def _save_plan(tmp_path: Path, issue: RefactorIssue, *, files_to_modify: list[str]) -> None:
    plan = RefactorPlan(
        task_id="ra-0001-test",
        issue_id=issue.id,
        goal="remove unused private code",
        refactoring_type=RefactoringType.REMOVE_DEAD_CODE,
        files_to_modify=files_to_modify,
        expected_changes=["delete unused private method"],
        out_of_scope=["do not modify files outside the plan"],
        risk_level=RiskLevel.LOW,
        risk_reasons=["LLM marked this private method as safe to remove"],
        verification_commands=["mvn test"],
        rollback_strategy="restore planned files from task snapshot",
        coverage_assessment=CoverageAssessment(
            has_related_test_class=False,
            related_tests=[],
            confidence="low",
            needs_characterization_test=False,
            recommendation="run verification after patch",
        ),
        requires_user_confirmation=True,
        context=JavaContext(
            issue_id=issue.id,
            target_file=issue.file_path,
            target_symbol=issue.symbol,
            source_excerpt="",
            related_tests=[],
            direct_callers=[],
        ),
        planning_source="llm-primary",
    )
    RefactorAgentStorage(tmp_path).save_plan(plan, issue)


class _FakePatchAssistant:
    def __init__(self, issue: RefactorIssue) -> None:
        self.issue = issue

    def generate_edit_plan(self, plan: RefactorPlan, issue: RefactorIssue) -> dict:
        del plan, issue
        return {
            "edits": [
                {
                    "file_path": self.issue.file_path,
                    "start_line": self.issue.start_line,
                    "end_line": self.issue.end_line,
                    "replacement": "",
                }
            ],
            "explanation": "LLM removes dead private method",
        }
