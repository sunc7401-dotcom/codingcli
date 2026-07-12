from __future__ import annotations

import asyncio
import builtins
from pathlib import Path

import pytest

from suncli_py.llm.models import ChatResponse, ToolCall, _Function
from suncli_py.refactor_agent.commands import RefactorAgentError, run_apply, run_plan, run_scan
from suncli_py.refactor_agent.llm_assistant import (
    RefactorLlmAssistant,
    RefactorLlmError,
    _reset_sync_loop_for_tests,
    _run_async,
    _sync_loop_id_for_tests,
)
from suncli_py.refactor_agent.models import (
    CoverageAssessment,
    Evidence,
    JavaContext,
    ProjectProfile,
    RefactoringType,
    RefactorIssue,
    RefactorPlan,
    RiskLevel,
    ScanResult,
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


def test_refactor_llm_sync_bridge_reuses_event_loop() -> None:
    _reset_sync_loop_for_tests()
    try:
        first_loop_id = _run_async(_current_loop_id())
        second_loop_id = _run_async(_current_loop_id())

        assert first_loop_id == second_loop_id
        assert first_loop_id == _sync_loop_id_for_tests()
    finally:
        _reset_sync_loop_for_tests()


def test_llm_provider_failure_is_wrapped_as_refactor_error(tmp_path: Path) -> None:
    source_path = _write_dead_code_java_file(tmp_path)
    assistant = RefactorLlmAssistant(_FailingLlmClient(RuntimeError("Event loop is closed")))

    with pytest.raises(RefactorLlmError, match="LLM request failed"):
        assistant.explain_issues(tmp_path, [_dead_code_issue(source_path)])


def test_scan_lets_llm_triage_rule_and_ast_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = _write_scan_long_method_java_file(tmp_path)
    monkeypatch.chdir(tmp_path)

    exit_code = run_scan(
        output_format="json",
        llm_assistant=_FakeDecisionAssistant(
            {
                "RA-0001": {
                    "priority": 1,
                    "severity": "high",
                    "risk_level": "medium",
                    "suggested_refactoring": "Extract Method",
                    "auto_applicable": True,
                    "requires_review": True,
                    "impact": "LLM decided the method is too hard to safely maintain",
                    "recommendation": "Extract a cohesive helper after checking tests",
                    "decision_reason": "AST metrics and source excerpt show repeated accumulator steps",
                }
            }
        ),
    )

    assert exit_code == 0
    issue = RefactorAgentStorage(tmp_path).load_scan_result().issues[0]
    assert issue.file_path == source_path.relative_to(tmp_path).as_posix()
    assert issue.severity == Severity.HIGH
    assert issue.risk_level == RiskLevel.MEDIUM
    assert issue.impact == "LLM decided the method is too hard to safely maintain"
    assert any(evidence.message == "LLM triage decision" for evidence in issue.evidence)


def test_plan_is_generated_by_llm_from_tool_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = _write_dead_code_java_file(tmp_path)
    issue = _dead_code_issue(source_path)
    RefactorAgentStorage(tmp_path).save_scan_result(
        ScanResult(
            profile=ProjectProfile(
                root=tmp_path,
                is_git_repo=True,
                is_maven_project=True,
                has_main_java=True,
                has_test_java=False,
                is_git_clean=True,
            ),
            issues=[issue],
        )
    )
    monkeypatch.chdir(tmp_path)

    exit_code = run_plan(
        issue_id=issue.id,
        llm_assistant=_FakePlanAssistant(
            {
                "goal": "LLM authored plan to remove unreachable private method",
                "refactoring_type": "Remove Dead Code",
                "files_to_modify": [issue.file_path],
                "expected_changes": ["delete only unusedPrivate"],
                "out_of_scope": ["do not touch public createOrder"],
                "risk_level": "low",
                "risk_reasons": ["private method has no direct callers"],
                "verification_commands": ["mvn test"],
                "rollback_strategy": "restore the task snapshot",
            }
        ),
    )

    assert exit_code == 0
    task_dir = next((tmp_path / ".paicli" / "refactor-agent" / "tasks").iterdir())
    plan = RefactorAgentStorage(tmp_path).load_task_plan(task_dir)[0]
    assert plan.goal == "LLM authored plan to remove unreachable private method"
    assert plan.planning_source == "llm-primary"
    assert plan.expected_changes == ["delete only unusedPrivate"]


def test_llm_plan_can_call_readonly_tools_before_final_json(tmp_path: Path) -> None:
    source_path = _write_dead_code_java_file(tmp_path)
    issue = _dead_code_issue(source_path)
    plan = _plan(issue)
    client = _FakeLlmClient(
        [
            ChatResponse(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(
                        id="tool-1",
                        function=_Function(
                            name="read_file",
                            arguments='{"file_path":"src/main/java/demo/OrderService.java","start_line":1,"end_line":12}',
                        ),
                    )
                ],
            ),
            '{"goal":"LLM used tool context before planning",'
            '"expected_changes":["delete unusedPrivate after reading exact source"],'
            '"out_of_scope":["do not change createOrder"],'
            '"risk_reasons":["tool read confirmed target method boundaries"],'
            '"verification_commands":["mvn test"]}',
        ]
    )
    assistant = RefactorLlmAssistant(client)

    planned = assistant.generate_plan(tmp_path, plan, issue)

    assert planned.goal == "LLM used tool context before planning"
    assert planned.planning_source == "llm-primary"
    assert client.tool_schema_seen is True
    assert any(message.role == "tool" and "unusedPrivate" in message.content for message in client.seen_messages)


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


def test_apply_repairs_failed_verification_with_llm_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = _write_dead_code_java_file(tmp_path)
    issue = _dead_code_issue(source_path)
    _save_plan(tmp_path, _plan(issue), issue)
    monkeypatch.chdir(tmp_path)
    return_line = next(
        index
        for index, line in enumerate(source_path.read_text(encoding="utf-8").splitlines(), start=1)
        if "return input + 1" in line
    )

    assistant = _FakePatchAssistant(
        {
            "edits": [
                {
                    "file_path": issue.file_path,
                    "start_line": return_line,
                    "end_line": return_line,
                    "replacement": "        return missingSymbol;",
                }
            ],
            "explanation": "bad first edit leaves an unresolved symbol",
        },
        repair_plan={
            "edits": [
                {
                    "file_path": issue.file_path,
                    "start_line": issue.start_line,
                    "end_line": issue.end_line,
                    "replacement": "",
                }
            ],
            "explanation": "repair only removes the private method",
        },
    )

    exit_code = run_apply(
        issue_id=issue.id,
        assume_yes=True,
        llm_assistant=assistant,
        max_repair_attempts=1,
        command_runner=_FailOnceRunner(),
    )

    assert exit_code == 0
    assert assistant.repair_calls == 1
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

    replacement = """    public int huge(int input) {
        int total = input;
        total = extractedHugeStep(total);
        return total;
    }

    private int extractedHugeStep(int total) {
        total += 1;
        total += 2;
        total += 3;
        total += 4;
        total += 5;
        total += 6;
        return total;
    }"""
    exit_code = run_apply(
        issue_id=issue.id,
        llm_assistant=_FakePatchAssistant(
            {
                "edits": [
                    {
                        "file_path": issue.file_path,
                        "start_line": issue.start_line,
                        "end_line": issue.end_line,
                        "replacement": replacement,
                    }
                ],
                "explanation": "LLM extracts accumulator block into private helper",
            }
        ),
    )

    assert exit_code == 0
    updated = source_path.read_text(encoding="utf-8")
    assert "total = extractedHugeStep(total);" in updated
    assert "private int extractedHugeStep(int total)" in updated
    assert "public int huge(int input)" in updated


class _FakeLlmClient:
    def __init__(self, responses: list[str | ChatResponse]) -> None:
        self._responses = responses
        self.tool_schema_seen = False
        self.seen_messages = []

    async def chat(self, *, messages, tools=None) -> ChatResponse:
        self.seen_messages = list(messages)
        self.tool_schema_seen = self.tool_schema_seen or bool(tools)
        response = self._responses.pop(0)
        if isinstance(response, ChatResponse):
            return response
        return ChatResponse(role="assistant", content=response)


class _FailingLlmClient:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def chat(self, *, messages, tools=None) -> ChatResponse:
        del messages, tools
        raise self.error


class _FakePatchAssistant:
    def __init__(self, edit_plan: dict, repair_plan: dict | None = None) -> None:
        self.edit_plan = edit_plan
        self.repair_plan = repair_plan
        self.repair_calls = 0

    def generate_edit_plan(self, plan: RefactorPlan, issue: RefactorIssue) -> dict:
        del plan, issue
        return self.edit_plan

    def generate_repair_edit_plan(self, root, plan, issue, verification, *, attempt: int) -> dict | None:
        del root, plan, issue, verification, attempt
        self.repair_calls += 1
        return self.repair_plan


class _FakeDecisionAssistant:
    def __init__(self, decisions: dict[str, dict]) -> None:
        self.decisions = decisions

    def triage_issues(self, root: Path, issues: list[RefactorIssue]) -> list[RefactorIssue]:
        del root
        from dataclasses import replace

        updated: list[RefactorIssue] = []
        for issue in issues:
            decision = self.decisions.get(issue.id, {})
            updated.append(
                replace(
                    issue,
                    severity=Severity(decision.get("severity", issue.severity)),
                    risk_level=RiskLevel(decision.get("risk_level", issue.risk_level)),
                    impact=decision.get("impact", issue.impact),
                    recommendation=decision.get("recommendation", issue.recommendation),
                    evidence=[
                        *issue.evidence,
                        Evidence("LLM triage decision", {"reason": decision.get("decision_reason", "")}),
                    ],
                )
            )
        return updated


class _FakePlanAssistant:
    def __init__(self, plan_data: dict) -> None:
        self.plan_data = plan_data

    def generate_plan(self, root: Path, plan: RefactorPlan, issue: RefactorIssue) -> RefactorPlan:
        del root, issue
        from dataclasses import replace

        return replace(
            plan,
            goal=self.plan_data["goal"],
            expected_changes=list(self.plan_data["expected_changes"]),
            out_of_scope=list(self.plan_data["out_of_scope"]),
            risk_reasons=list(self.plan_data["risk_reasons"]),
            verification_commands=list(self.plan_data["verification_commands"]),
            rollback_strategy=self.plan_data["rollback_strategy"],
            planning_source="llm-primary",
        )


class _FailOnceRunner:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, command, cwd):
        import subprocess

        del cwd
        self.calls += 1
        if self.calls == 1:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="compile failed")
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")


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


def _write_scan_long_method_java_file(root: Path) -> Path:
    _write_minimal_repo(root)
    source_dir = root / "src" / "main" / "java" / "demo"
    source_dir.mkdir(parents=True, exist_ok=True)
    source_path = source_dir / "LargeMathService.java"
    body = "\n".join(f"        total += {index};" for index in range(90))
    source_path.write_text(
        f"""
package demo;

public class LargeMathService {{
    public int huge(int input) {{
        int total = input;
{body}
        return total;
    }}
}}
""".lstrip(),
        encoding="utf-8",
    )
    return source_path


def _write_minimal_repo(root: Path) -> None:
    (root / ".git").mkdir(exist_ok=True)
    (root / "pom.xml").write_text(
        """
<project>
  <modelVersion>4.0.0</modelVersion>
  <groupId>demo</groupId>
  <artifactId>sample</artifactId>
  <version>1.0.0</version>
  <build>
    <plugins>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-pmd-plugin</artifactId>
        <version>3.28.0</version>
      </plugin>
    </plugins>
  </build>
</project>
""".strip(),
        encoding="utf-8",
    )


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


async def _current_loop_id() -> int:
    return id(asyncio.get_running_loop())
