from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from suncli_py.llm.models import ChatResponse, ToolCall, _Function
from suncli_py.refactor_agent.assistant.orchestrator import RefactorAgentOrchestrator
from suncli_py.refactor_agent.core.models import (
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
from suncli_py.refactor_agent.core.storage import RefactorAgentStorage
from suncli_py.refactor_agent.execution.patch_validator import AstPatchValidator
from suncli_py.refactor_agent.execution.patcher import RefactorPatcher
from suncli_py.refactor_agent.execution.rollback import TaskRollbacker
from suncli_py.refactor_agent.execution.test_generator import (
    GeneratedTestFileManager,
)
from suncli_py.refactor_agent.execution.test_generator import (
    TestGenerationError as GenerationError,
)
from suncli_py.refactor_agent.execution.verifier import (
    COVERAGE_COMMAND,
    DEFAULT_VERIFICATION_COMMANDS,
    JACOCO_TEST_COMMAND,
    TEST_COMMAND,
    TEST_COMPILE_COMMAND,
    PreModificationVerifier,
)


def test_successful_jacoco_without_report_is_treated_as_test_gap(tmp_path: Path) -> None:
    _, issue, plan, _ = _project(tmp_path, covered=False)
    (tmp_path / "target" / "site" / "jacoco" / "jacoco.xml").unlink()

    result = PreModificationVerifier(tmp_path, command_runner=_always_successful_runner).verify(plan, issue)

    assert result.status == "coverage_gap"
    assert result.requires_test_generation is True
    assert result.infrastructure_error == ""


def test_coverage_gap_generates_test_before_modifier_and_keeps_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, issue, plan, task_dir = _project(tmp_path, covered=False)
    monkeypatch.setattr(AstPatchValidator, "validate", lambda self, plan, task_dir: [])
    test_path = "src/test/java/demo/OrderServiceCharacterizationTest.java"
    client = _ScriptedClient(
        [
            _test_write_tool(test_path),
            _tool_call("test-precheck", "run_generated_test_precheck", {}),
            _test_generator_final(),
            _modifier_tool(issue),
            _modifier_final(),
            _verification_tools(),
            _verifier_final(True),
        ]
    )

    result = RefactorAgentOrchestrator(
        root=tmp_path,
        client=client,
        storage=RefactorAgentStorage(tmp_path),
        command_runner=_CoverageAwareRunner(tmp_path, issue),
    ).run(plan=plan, issue=issue, task_dir=task_dir, max_repair_attempts=0)

    assert result.success is True
    assert result.attempts == 1
    assert result.generated_tests == [test_path]
    assert (tmp_path / test_path).is_file()
    assert "unusedPrivate" not in source.read_text(encoding="utf-8")
    assert result.pre_modification is not None
    assert result.pre_modification.status == "ready_with_generated_tests"
    assert result.pre_modification.coverage.target_file_lines_covered > 0
    combined_diff = (task_dir / "patch.diff").read_text(encoding="utf-8")
    assert f"b/{test_path}" in combined_diff
    assert f"b/{issue.file_path}" in combined_diff
    generator_record = json.loads(
        (task_dir / "preflight" / "test_generator.json").read_text(encoding="utf-8")
    )
    assert generator_record["message"]["from_role"] == "TEST_GENERATOR"
    generated_test_commands = [command["command"] for command in generator_record["commands"]]
    assert generated_test_commands == [
        TEST_COMPILE_COMMAND,
        TEST_COMMAND,
        JACOCO_TEST_COMMAND,
        COVERAGE_COMMAND,
    ]
    assert sum(command.endswith(" test") for command in generated_test_commands) == 2


def test_generated_test_policy_rejects_trivial_or_disabled_tests(tmp_path: Path) -> None:
    _, issue, _, task_dir = _project(tmp_path, covered=False)
    manager = GeneratedTestFileManager(tmp_path, issue, task_dir, task_dir / "preflight")
    test_path = manager.allowed_files[0]

    with pytest.raises(GenerationError, match="constant/trivial"):
        manager.apply(
            [
                {
                    "file_path": test_path,
                    "content": (
                        "package demo;\nimport org.junit.jupiter.api.Test;\n"
                        "class OrderServiceCharacterizationTest {\n"
                        "  @Test void fake() { new OrderService(); assertTrue(true); }\n}\n"
                    ),
                }
            ]
        )

    assert not (tmp_path / test_path).exists()


def test_final_verifier_rejection_rolls_back_production_and_generated_test(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, issue, plan, task_dir = _project(tmp_path, covered=False)
    original = source.read_text(encoding="utf-8")
    monkeypatch.setattr(AstPatchValidator, "validate", lambda self, plan, task_dir: [])
    test_path = "src/test/java/demo/OrderServiceCharacterizationTest.java"
    client = _ScriptedClient(
        [
            _test_write_tool(test_path),
            _tool_call("test-precheck", "run_generated_test_precheck", {}),
            _test_generator_final(),
            _modifier_tool(issue),
            _modifier_final(),
            _verification_tools(),
            _verifier_final(False),
        ]
    )

    result = RefactorAgentOrchestrator(
        root=tmp_path,
        client=client,
        storage=RefactorAgentStorage(tmp_path),
        command_runner=_CoverageAwareRunner(tmp_path, issue),
    ).run(plan=plan, issue=issue, task_dir=task_dir, max_repair_attempts=0)

    assert result.success is False
    assert result.rollback is not None and result.rollback.status == "rolled_back"
    assert source.read_text(encoding="utf-8") == original
    assert not (tmp_path / test_path).exists()
    assert test_path in result.rollback.restored_files


def test_generated_guard_tampering_during_verification_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, issue, plan, task_dir = _project(tmp_path, covered=False)
    original = source.read_text(encoding="utf-8")
    monkeypatch.setattr(AstPatchValidator, "validate", lambda self, plan, task_dir: [])
    test_path = "src/test/java/demo/OrderServiceCharacterizationTest.java"
    client = _ScriptedClient(
        [
            _test_write_tool(test_path),
            _tool_call("test-precheck", "run_generated_test_precheck", {}),
            _test_generator_final(),
            _modifier_tool(issue),
            _modifier_final(),
            _verification_tools(),
            _verifier_final(True),
        ]
    )

    result = RefactorAgentOrchestrator(
        root=tmp_path,
        client=client,
        storage=RefactorAgentStorage(tmp_path),
        command_runner=_CoverageAwareRunner(tmp_path, issue, tamper_after_modification=True),
    ).run(plan=plan, issue=issue, task_dir=task_dir, max_repair_attempts=0)

    assert result.success is False
    assert "Generated test guards changed unexpectedly" in result.error
    assert source.read_text(encoding="utf-8") == original
    assert not (tmp_path / test_path).exists()


def test_repair_rollback_preserves_generated_test_until_second_attempt_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, issue, plan, task_dir = _project(tmp_path, covered=False)
    monkeypatch.setattr(AstPatchValidator, "validate", lambda self, plan, task_dir: [])
    test_path = "src/test/java/demo/OrderServiceCharacterizationTest.java"
    return_line = next(
        number
        for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1)
        if "return input + 1" in line
    )
    client = _ScriptedClient(
        [
            _test_write_tool(test_path),
            _tool_call("test-precheck", "run_generated_test_precheck", {}),
            _test_generator_final(),
            _modifier_line_tool(issue.file_path, return_line, "        return missingSymbol;"),
            _modifier_final(),
            _verification_tools(),
            _verifier_final(True),
            _modifier_tool(issue),
            _modifier_final(),
            _verification_tools(),
            _verifier_final(True),
        ]
    )

    result = RefactorAgentOrchestrator(
        root=tmp_path,
        client=client,
        storage=RefactorAgentStorage(tmp_path),
        command_runner=_CoverageAwareRunner(tmp_path, issue, fail_bad_compile=True),
    ).run(plan=plan, issue=issue, task_dir=task_dir, max_repair_attempts=1)

    assert result.success is True
    assert result.attempts == 2
    assert (tmp_path / test_path).is_file()
    recovery = json.loads(
        (task_dir / "attempts" / "02" / "pre_repair_rollback.json").read_text(encoding="utf-8")
    )
    assert issue.file_path in recovery["restored_files"]
    assert test_path not in recovery["restored_files"]


def test_manual_rollback_detects_generated_test_edit_and_force_removes_it(tmp_path: Path) -> None:
    _, issue, plan, task_dir = _project(tmp_path, covered=False)
    RefactorPatcher(tmp_path).ensure_initial_snapshot(plan, task_dir)
    manager = GeneratedTestFileManager(tmp_path, issue, task_dir, task_dir / "preflight")
    test_path = manager.allowed_files[0]
    manager.apply([{"file_path": test_path, "content": _generated_test_content()}])
    generated = tmp_path / test_path
    generated.write_text(generated.read_text(encoding="utf-8") + "// user edit\n", encoding="utf-8")

    conflict = TaskRollbacker(tmp_path).rollback(task_dir, force=False)
    assert conflict.status == "conflict"
    assert test_path in conflict.conflicts
    assert generated.is_file()

    forced = TaskRollbacker(tmp_path).rollback(task_dir, force=True)
    assert forced.status == "rolled_back"
    assert not generated.exists()


class _ScriptedClient:
    def __init__(self, responses: list[ChatResponse]) -> None:
        self.responses = list(responses)

    async def chat(self, *, messages, tools=None) -> ChatResponse:
        del messages, tools
        if not self.responses:
            raise AssertionError("No scripted response remains")
        return self.responses.pop(0)

    @property
    def max_context_window(self) -> int:
        return 128_000


class _CoverageAwareRunner:
    def __init__(
        self,
        root: Path,
        issue: RefactorIssue,
        *,
        fail_bad_compile: bool = False,
        tamper_after_modification: bool = False,
    ) -> None:
        self.root = root
        self.issue = issue
        self.fail_bad_compile = fail_bad_compile
        self.tamper_after_modification = tamper_after_modification
        self.tampered = False

    def __call__(self, command, cwd):
        del cwd
        source = self.root / self.issue.file_path
        if (
            self.fail_bad_compile
            and command[-1] == "compile"
            and "missingSymbol" in source.read_text(encoding="utf-8")
        ):
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="missingSymbol")
        if any("jacoco-maven-plugin:report" in part for part in command):
            test_file = self.root / "src" / "test" / "java" / "demo" / "OrderServiceCharacterizationTest.java"
            _write_jacoco_xml(self.root, self.issue.start_line, covered=test_file.is_file())
        test_file = self.root / "src" / "test" / "java" / "demo" / "OrderServiceCharacterizationTest.java"
        if (
            self.tamper_after_modification
            and not self.tampered
            and command[-1] == "test"
            and test_file.is_file()
            and "unusedPrivate" not in source.read_text(encoding="utf-8")
        ):
            test_file.write_text(test_file.read_text(encoding="utf-8") + "// tampered\n", encoding="utf-8")
            self.tampered = True
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")


def _always_successful_runner(command, cwd):
    del cwd
    return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")


def _test_write_tool(test_path: str) -> ChatResponse:
    return _tool_call(
        "test-write",
        "apply_test_edits",
        {"files": [{"file_path": test_path, "content": _generated_test_content()}]},
    )


def _generated_test_content() -> str:
    return """package demo;

import static org.junit.jupiter.api.Assertions.assertEquals;
import org.junit.jupiter.api.Test;

class OrderServiceCharacterizationTest {
    @Test
    void preservesCreateOrderResult() {
        assertEquals(2, new OrderService().createOrder(1));
    }
}
"""


def _test_generator_final() -> ChatResponse:
    return ChatResponse(
        role="assistant",
        content=(
            '{"status":"created","summary":"guard created","test_files":[],'
            '"assertion_intents":["lock result"],"risk_notes":[]}'
        ),
    )


def _modifier_tool(issue: RefactorIssue) -> ChatResponse:
    return _modifier_line_tool(issue.file_path, issue.start_line, "", issue.end_line)


def _modifier_line_tool(
    file_path: str,
    start_line: int,
    replacement: str,
    end_line: int | None = None,
) -> ChatResponse:
    return _tool_call(
        "apply",
        "apply_edits",
        {
            "edits": [
                {
                    "file_path": file_path,
                    "start_line": start_line,
                    "end_line": end_line or start_line,
                    "replacement": replacement,
                }
            ],
            "explanation": "controlled edit",
        },
    )


def _modifier_final() -> ChatResponse:
    return ChatResponse(
        role="assistant",
        content='{"status":"applied","summary":"done","changed_files":[],"risk_notes":[]}',
    )


def _verification_tools() -> ChatResponse:
    calls = [
        ToolCall(
            id=f"command-{index}",
            function=_Function(name="run_verification_command", arguments=json.dumps({"command": command})),
        )
        for index, command in enumerate(DEFAULT_VERIFICATION_COMMANDS, start=1)
    ]
    calls.extend(
        [
            ToolCall(id="diff", function=_Function(name="inspect_diff", arguments="{}")),
            ToolCall(id="coverage", function=_Function(name="get_coverage_assessment", arguments="{}")),
        ]
    )
    return ChatResponse(role="assistant", content="", tool_calls=calls)


def _verifier_final(approved: bool) -> ChatResponse:
    return ChatResponse(
        role="assistant",
        content=json.dumps(
            {
                "approved": approved,
                "status": "passed" if approved else "failed",
                "summary": "verified" if approved else "rejected",
                "issues": [] if approved else ["patch rejected"],
                "suggestions": [] if approved else ["repair patch"],
                "evidence_tools": ["compile", "test", "coverage", "diff"],
            }
        ),
    )


def _tool_call(call_id: str, name: str, arguments: dict[str, object]) -> ChatResponse:
    return ChatResponse(
        role="assistant",
        content="",
        tool_calls=[ToolCall(id=call_id, function=_Function(name=name, arguments=json.dumps(arguments)))],
    )


def _project(
    root: Path,
    *,
    covered: bool,
) -> tuple[Path, RefactorIssue, RefactorPlan, Path]:
    source = root / "src" / "main" / "java" / "demo" / "OrderService.java"
    source.parent.mkdir(parents=True)
    source.write_text(
        """package demo;

public class OrderService {
    public int createOrder(int input) {
        return input + 1;
    }

    private int unusedPrivate(int value) {
        return value * 2;
    }
}
""",
        encoding="utf-8",
    )
    (root / "pom.xml").write_text("<project />", encoding="utf-8")
    issue = RefactorIssue(
        id="RA-0001",
        type=SmellType.DEAD_CODE,
        severity=Severity.LOW,
        file_path=source.relative_to(root).as_posix(),
        start_line=8,
        end_line=10,
        symbol="unusedPrivate",
        evidence=[Evidence("test", {})],
        impact="unused code",
        recommendation="remove it",
        suggested_refactoring=RefactoringType.REMOVE_DEAD_CODE,
        risk_level=RiskLevel.LOW,
    )
    plan = RefactorPlan(
        task_id="ra-0001-preflight",
        issue_id=issue.id,
        goal="remove unused private method",
        refactoring_type=RefactoringType.REMOVE_DEAD_CODE,
        files_to_modify=[issue.file_path],
        expected_changes=["remove unusedPrivate"],
        out_of_scope=["public API", "test edits by modifier"],
        risk_level=RiskLevel.LOW,
        risk_reasons=[],
        verification_commands=list(DEFAULT_VERIFICATION_COMMANDS[:2]),
        rollback_strategy="restore snapshot and generated tests",
        coverage_assessment=CoverageAssessment(
            has_related_test_class=False,
            related_tests=[],
            confidence="low",
            needs_characterization_test=True,
            recommendation="generate a behavior-locking test",
        ),
        context=JavaContext(
            issue_id=issue.id,
            target_file=issue.file_path,
            target_symbol=issue.symbol,
            source_excerpt="",
            related_tests=[],
            direct_callers=[],
            warnings=[],
        ),
        planning_source="test",
    )
    storage = RefactorAgentStorage(root)
    storage.save_plan(plan, issue)
    _write_jacoco_xml(root, issue.start_line, covered=covered)
    return source, issue, plan, storage.task_dir(plan.task_id)


def _write_jacoco_xml(root: Path, start_line: int, *, covered: bool) -> None:
    report_dir = root / "target" / "site" / "jacoco"
    report_dir.mkdir(parents=True, exist_ok=True)
    ci = 1 if covered else 0
    report_dir.joinpath("jacoco.xml").write_text(
        f"""
<report name="demo">
  <package name="demo">
    <sourcefile name="OrderService.java">
      <line nr="{start_line}" mi="{1 - ci}" ci="{ci}"/>
      <line nr="{start_line + 1}" mi="{1 - ci}" ci="{ci}"/>
      <line nr="{start_line + 2}" mi="{1 - ci}" ci="{ci}"/>
    </sourcefile>
  </package>
</report>
""".strip(),
        encoding="utf-8",
    )
