from __future__ import annotations

import builtins
from pathlib import Path

import pytest

from suncli_py.llm.models import ChatResponse
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


def test_llm_assistant_explains_issues_and_enhances_plan(tmp_path: Path) -> None:
    source_path = _write_dead_code_java_file(tmp_path)
    issue = _dead_code_issue(source_path)
    plan = _plan(issue)
    assistant = RefactorLlmAssistant(
        _FakeLlmClient(
            [
                (
                    '{"impact":"LLM explains maintainability impact",'
                    '"recommendation":"LLM recommends guarded removal",'
                    '"risk_notes":["check reflection"],"confidence":"high"}'
                ),
                (
                    '{"goal":"LLM refined goal","expected_changes":["delete private method only"],'
                    '"out_of_scope":["public API changes"],"risk_reasons":["LLM risk"],'
                    '"verification_commands":["mvn -q -DskipTests compile","mvn test"]}'
                ),
            ]
        )
    )

    explained = assistant.explain_issues(tmp_path, [issue])
    enhanced = assistant.enhance_plan(plan, issue)

    assert explained[0].impact == "LLM explains maintainability impact"
    assert explained[0].recommendation == "LLM recommends guarded removal"
    assert any(evidence.message == "LLM risk notes" for evidence in explained[0].evidence)
    assert enhanced.goal == "LLM refined goal"
    assert enhanced.planning_source == "llm-enhanced"
    assert "public API changes" in enhanced.out_of_scope


def test_apply_uses_llm_controlled_edit_operations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = _write_dead_code_java_file(tmp_path)
    issue = _dead_code_issue(source_path)
    _save_plan(tmp_path, _plan(issue), issue)
    monkeypatch.chdir(tmp_path)

    exit_code = run_apply(
        issue_id=issue.id,
        assume_yes=True,
        llm_assistant=_FakePatchAssistant(
            {
                "edits": [
                    {
                        "file_path": issue.file_path,
                        "start_line": issue.start_line,
                        "end_line": issue.end_line,
                        "replacement": "",
                    }
                ],
                "explanation": "LLM removes dead private method",
            }
        ),
    )

    assert exit_code == 0
    updated = source_path.read_text(encoding="utf-8")
    assert "unusedPrivate" not in updated
    assert "createOrder" in updated


def test_ast_patch_validator_rejects_llm_public_signature_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = _write_dead_code_java_file(tmp_path)
    issue = _dead_code_issue(source_path)
    _save_plan(tmp_path, _plan(issue), issue)
    original = source_path.read_text(encoding="utf-8")
    public_line = next(
        index
        for index, line in enumerate(original.splitlines(), start=1)
        if "public int createOrder" in line
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(RefactorAgentError, match="AST patch validation failed"):
        run_apply(
            issue_id=issue.id,
            assume_yes=True,
            llm_assistant=_FakePatchAssistant(
                {
                    "edits": [
                        {
                            "file_path": issue.file_path,
                            "start_line": public_line,
                            "end_line": public_line,
                            "replacement": "    public long createOrder(int input) {",
                        }
                    ],
                    "explanation": "unsafe public API edit",
                }
            ),
        )

    assert source_path.read_text(encoding="utf-8") == original


def test_apply_extracts_conservative_method_for_long_method(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = _write_long_method_java_file(tmp_path)
    issue = _long_method_issue(source_path)
    _save_plan(
        tmp_path,
        _plan(
            issue,
            risk_level=RiskLevel.MEDIUM,
            refactoring_type=RefactoringType.EXTRACT_METHOD,
        ),
        issue,
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(builtins, "input", lambda _: "y")

    exit_code = run_apply(issue_id=issue.id)

    assert exit_code == 0
    updated = source_path.read_text(encoding="utf-8")
    assert "total = extractedHugeStep(total);" in updated
    assert "private int extractedHugeStep(int total)" in updated
    assert "public int huge(int input)" in updated


class _FakeLlmClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses

    async def chat(self, *, messages, tools=None) -> ChatResponse:
        del messages, tools
        return ChatResponse(role="assistant", content=self._responses.pop(0))


class _FakePatchAssistant:
    def __init__(self, edit_plan: dict) -> None:
        self.edit_plan = edit_plan

    def generate_edit_plan(self, plan: RefactorPlan, issue: RefactorIssue) -> dict:
        del plan, issue
        return self.edit_plan


def _write_dead_code_java_file(root: Path) -> Path:
    _write_minimal_repo(root)
    source_dir = root / "src" / "main" / "java" / "demo"
    source_dir.mkdir(parents=True, exist_ok=True)
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


def _write_long_method_java_file(root: Path) -> Path:
    _write_minimal_repo(root)
    source_dir = root / "src" / "main" / "java" / "demo"
    source_dir.mkdir(parents=True, exist_ok=True)
    source_path = source_dir / "MathService.java"
    source_path.write_text(
        """
package demo;

public class MathService {
    public int huge(int input) {
        int total = input;
        total += 1;
        total += 2;
        total += 3;
        total += 4;
        total += 5;
        total += 6;
        return total;
    }
}
""".lstrip(),
        encoding="utf-8",
    )
    return source_path


def _write_minimal_repo(root: Path) -> None:
    (root / ".git").mkdir(exist_ok=True)
    (root / "pom.xml").write_text("<project />", encoding="utf-8")


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


def _long_method_issue(source_path: Path) -> RefactorIssue:
    lines = source_path.read_text(encoding="utf-8").splitlines()
    start_line = next(index for index, line in enumerate(lines, start=1) if "public int huge" in line)
    end_line = next(index for index, line in enumerate(lines, start=1) if index > start_line and line == "    }")
    return RefactorIssue(
        id="RA-0002",
        type=SmellType.LONG_METHOD,
        severity=Severity.MEDIUM,
        file_path="src/main/java/demo/MathService.java",
        symbol="huge",
        start_line=start_line,
        end_line=end_line,
        evidence=[Evidence("method is long enough for extract-method demo", {"lines": end_line - start_line + 1})],
        impact="long method hides steps",
        recommendation="extract a cohesive accumulator block",
        suggested_refactoring=RefactoringType.EXTRACT_METHOD,
        auto_applicable=True,
        risk_level=RiskLevel.MEDIUM,
        requires_review=True,
    )


def _plan(
    issue: RefactorIssue,
    *,
    risk_level: RiskLevel = RiskLevel.LOW,
    refactoring_type: RefactoringType | None = None,
) -> RefactorPlan:
    return RefactorPlan(
        task_id=f"{issue.id.lower()}-test",
        issue_id=issue.id,
        goal="small safe refactor",
        refactoring_type=refactoring_type or issue.suggested_refactoring,
        files_to_modify=[issue.file_path],
        expected_changes=["modify only the target code"],
        out_of_scope=["do not change public API"],
        risk_level=risk_level,
        risk_reasons=["test risk"],
        verification_commands=["mvn test"],
        rollback_strategy="restore planned files from snapshot",
        coverage_assessment=CoverageAssessment(
            has_related_test_class=False,
            related_tests=[],
            confidence="low",
            needs_characterization_test=False,
            recommendation="run tests",
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
        planning_source="test",
    )


def _save_plan(tmp_path: Path, plan: RefactorPlan, issue: RefactorIssue) -> None:
    RefactorAgentStorage(tmp_path).save_plan(plan, issue)
