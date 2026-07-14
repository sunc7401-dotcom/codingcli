from __future__ import annotations

import json
from pathlib import Path

import pytest

from suncli_py.refactor_agent.core.models import (
    Evidence,
    ProjectProfile,
    RefactoringType,
    RefactorIssue,
    RiskLevel,
    ScanResult,
    Severity,
    SmellType,
)
from suncli_py.refactor_agent.core.storage import RefactorAgentStorage
from suncli_py.refactor_agent.interface.commands import RefactorAgentError, run_plan


def test_plan_generates_structured_files_from_scanned_issue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_java_project(tmp_path)
    issue = _issue()
    storage = RefactorAgentStorage(tmp_path)
    storage.save_scan_result(
        ScanResult(
            profile=ProjectProfile(
                root=tmp_path,
                is_git_repo=True,
                is_maven_project=True,
                has_main_java=True,
                has_test_java=True,
                is_git_clean=True,
            ),
            issues=[issue],
        )
    )
    monkeypatch.chdir(tmp_path)

    exit_code = run_plan(issue_id="RA-0001", llm_assistant=_FakePlanAssistant())

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "重构计划" in output
    assert "RA-0001" in output

    task_dirs = list((tmp_path / ".paicli" / "refactor-agent" / "tasks").iterdir())
    assert len(task_dirs) == 1
    plan_json_path = task_dirs[0] / "plan.json"
    plan_md_path = task_dirs[0] / "plan.md"
    assert plan_json_path.is_file()
    assert plan_md_path.is_file()

    plan = json.loads(plan_json_path.read_text(encoding="utf-8"))
    assert plan["issue_id"] == "RA-0001"
    assert plan["files_to_modify"] == ["src/main/java/demo/OrderService.java"]
    assert plan["coverage_assessment"]["has_related_test_class"] is True
    assert plan["coverage_assessment"]["related_tests"] == ["src/test/java/demo/OrderServiceTest.java"]
    assert "requires_user_confirmation" not in plan
    assert plan["planning_source"] == "llm-primary"
    assert "mvn test" in plan["verification_commands"]


def test_plan_requires_existing_scan_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(RefactorAgentError, match="先运行 refactor-agent scan"):
        run_plan(issue_id="RA-0001")


def _write_java_project(root: Path) -> None:
    (root / ".git").mkdir()
    main_dir = root / "src" / "main" / "java" / "demo"
    test_dir = root / "src" / "test" / "java" / "demo"
    main_dir.mkdir(parents=True)
    test_dir.mkdir(parents=True)
    (root / "pom.xml").write_text("<project />", encoding="utf-8")
    (main_dir / "OrderService.java").write_text(
        """
package demo;

public class OrderService {
    public int createOrder(int input) {
        return input + 1;
    }
}
""",
        encoding="utf-8",
    )
    (test_dir / "OrderServiceTest.java").write_text(
        """
package demo;

class OrderServiceTest {
}
""",
        encoding="utf-8",
    )


def _issue() -> RefactorIssue:
    return RefactorIssue(
        id="RA-0001",
        type=SmellType.LONG_METHOD,
        severity=Severity.MEDIUM,
        file_path="src/main/java/demo/OrderService.java",
        symbol="createOrder",
        start_line=5,
        end_line=7,
        evidence=[Evidence("方法行数超过阈值。", {"lines": 90})],
        impact="长方法会让职责边界模糊。",
        recommendation="使用 Extract Method 小步拆分。",
        suggested_refactoring=RefactoringType.EXTRACT_METHOD,
        risk_level=RiskLevel.MEDIUM,
    )


class _FakePlanAssistant:
    def generate_plan(self, root: Path, plan, issue):
        del root, issue
        from dataclasses import replace

        return replace(plan, planning_source="llm-primary")
