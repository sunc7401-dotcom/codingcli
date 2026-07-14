from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

from suncli_py.refactor_agent.commands import run_apply, run_characterize, run_rollback, run_verify
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


def test_verify_runs_maven_and_records_jacoco_coverage(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    source_path = _write_java_file(tmp_path)
    issue = _dead_code_issue(source_path)
    _save_plan(tmp_path, issue)
    _write_jacoco_xml(tmp_path, issue.start_line)
    task_dir = next((tmp_path / ".paicli" / "refactor-agent" / "tasks").iterdir())
    (task_dir / "patch.diff").write_text(
        "diff --git a/src/main/java/demo/OrderService.java b/src/main/java/demo/OrderService.java\n",
        encoding="utf-8",
    )
    (task_dir / "diff_summary.txt").write_text("summary", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    exit_code = run_verify(issue_id="RA-0001", command_runner=_successful_runner)

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "verify passed" in output
    verification = json.loads((task_dir / "verification.json").read_text(encoding="utf-8"))
    assert verification["status"] == "passed"
    assert verification["coverage"]["jacoco_report_found"] is True
    assert verification["coverage"]["changed_lines_covered"] == 3
    assert (task_dir / "report.md").is_file()
    assert (tmp_path / ".paicli" / "refactor-agent" / "reports" / "latest.md").is_file()


def test_characterize_writes_candidate_test_after_confirmation_and_precheck(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_path = _write_java_file(tmp_path)
    _save_plan(tmp_path, _dead_code_issue(source_path))
    monkeypatch.chdir(tmp_path)

    exit_code = run_characterize(issue_id="RA-0001", assume_yes=True, command_runner=_successful_runner)

    assert exit_code == 0
    test_file = tmp_path / "src" / "test" / "java" / "demo" / "OrderServiceCharacterizationTest.java"
    assert test_file.is_file()
    task_dir = next((tmp_path / ".paicli" / "refactor-agent" / "tasks").iterdir())
    plan = json.loads((task_dir / "characterization_plan.json").read_text(encoding="utf-8"))
    assert plan["user_confirmed"] is True
    assert plan["pre_refactor_test_result"]["exit_code"] == 0
    assert plan["usable_as_refactor_guard"] is True


def test_rollback_detects_conflict_then_restores_with_confirmation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_path = _write_java_file(tmp_path)
    issue = _dead_code_issue(source_path)
    _save_plan(tmp_path, issue)
    monkeypatch.chdir(tmp_path)
    assert run_apply(issue_id="RA-0001", assume_yes=True, llm_assistant=_FakePatchAssistant(issue)) == 0
    assert "unusedPrivate" not in source_path.read_text(encoding="utf-8")

    source_path.write_text(source_path.read_text(encoding="utf-8").replace("input + 1", "input + 2"), encoding="utf-8")

    assert run_rollback(assume_yes=False) == 1
    assert "input + 2" in source_path.read_text(encoding="utf-8")

    assert run_rollback(assume_yes=True) == 0
    restored = source_path.read_text(encoding="utf-8")
    assert "unusedPrivate" in restored
    assert "input + 1" in restored
    task_dir = next((tmp_path / ".paicli" / "refactor-agent" / "tasks").iterdir())
    rollback = json.loads((task_dir / "rollback.json").read_text(encoding="utf-8"))
    assert rollback["status"] == "rolled_back"
    report = (task_dir / "report.md").read_text(encoding="utf-8")
    assert "rolled_back" in report


def _successful_runner(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    del cwd
    return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")


def _write_java_file(root: Path) -> Path:
    (root / ".git").mkdir()
    source_dir = root / "src" / "main" / "java" / "demo"
    source_dir.mkdir(parents=True)
    (root / "pom.xml").write_text("<project />", encoding="utf-8")
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
        risk_level=RiskLevel.LOW,
    )


def _save_plan(tmp_path: Path, issue: RefactorIssue) -> None:
    plan = RefactorPlan(
        task_id="ra-0001-test",
        issue_id=issue.id,
        goal="remove unused private code",
        refactoring_type=RefactoringType.REMOVE_DEAD_CODE,
        files_to_modify=[issue.file_path],
        expected_changes=["delete unused private method"],
        out_of_scope=["do not modify files outside the plan"],
        risk_level=RiskLevel.LOW,
        risk_reasons=["low-risk private dead code"],
        verification_commands=["mvn test"],
        rollback_strategy="restore planned files from snapshot",
        coverage_assessment=CoverageAssessment(
            has_related_test_class=False,
            related_tests=[],
            confidence="low",
            needs_characterization_test=True,
            recommendation="add characterization test",
        ),
        context=JavaContext(
            issue_id=issue.id,
            target_file=issue.file_path,
            target_symbol=issue.symbol,
            source_excerpt="",
            related_tests=[],
            direct_callers=[],
        ),
        planning_source="test",
    )
    RefactorAgentStorage(tmp_path).save_plan(plan, issue)


def _write_jacoco_xml(root: Path, start_line: int) -> None:
    report_dir = root / "target" / "site" / "jacoco"
    report_dir.mkdir(parents=True)
    report_dir.joinpath("jacoco.xml").write_text(
        f"""
<report name="demo">
  <package name="demo">
    <sourcefile name="OrderService.java">
      <line nr="{start_line}" mi="0" ci="1"/>
      <line nr="{start_line + 1}" mi="0" ci="1"/>
      <line nr="{start_line + 2}" mi="0" ci="1"/>
    </sourcefile>
  </package>
</report>
""".strip(),
        encoding="utf-8",
    )


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
