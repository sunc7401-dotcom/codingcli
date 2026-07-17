from __future__ import annotations

import builtins
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from suncli_py.llm.models import ChatResponse, ToolCall, _Function
from suncli_py.refactor_agent.assistant.llm_assistant import RefactorLlmAssistant
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
from suncli_py.refactor_agent.execution.patcher import PatchError, RefactorPatcher
from suncli_py.refactor_agent.execution.verifier import DEFAULT_VERIFICATION_COMMANDS
from suncli_py.refactor_agent.interface.commands import RefactorAgentError, run_apply


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
    monkeypatch.setattr(AstPatchValidator, "validate", lambda self, plan, task_dir: [])

    exit_code = run_apply(
        issue_id="RA-0001",
        assume_yes=True,
        llm_assistant=_FakePatchAssistant(issue),
        max_repair_attempts=0,
        command_runner=_successful_runner,
    )

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


def test_apply_writes_high_risk_change_after_interactive_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = _write_java_file(tmp_path)
    issue = _dead_code_issue(source_path, risk_level=RiskLevel.HIGH)
    _save_plan(tmp_path, issue, files_to_modify=[issue.file_path])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(builtins, "input", lambda _: "y")
    monkeypatch.setattr(AstPatchValidator, "validate", lambda self, plan, task_dir: [])

    exit_code = run_apply(
        issue_id=issue.id,
        llm_assistant=_FakePatchAssistant(issue),
        max_repair_attempts=0,
        command_runner=_successful_runner,
    )

    assert exit_code == 0
    assert "unusedPrivate" not in source_path.read_text(encoding="utf-8")


def test_apply_yes_flag_writes_high_risk_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = _write_java_file(tmp_path)
    issue = _dead_code_issue(source_path, risk_level=RiskLevel.HIGH)
    _save_plan(tmp_path, issue, files_to_modify=[issue.file_path])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(AstPatchValidator, "validate", lambda self, plan, task_dir: [])

    exit_code = run_apply(
        issue_id=issue.id,
        assume_yes=True,
        llm_assistant=_FakePatchAssistant(issue),
        max_repair_attempts=0,
        command_runner=_successful_runner,
    )

    assert exit_code == 0
    assert "unusedPrivate" not in source_path.read_text(encoding="utf-8")


def test_legacy_boolean_fields_are_ignored_when_loading_saved_models(tmp_path: Path) -> None:
    source_path = _write_java_file(tmp_path)
    issue = _dead_code_issue(source_path)
    _save_plan(tmp_path, issue, files_to_modify=[issue.file_path])
    task_dir = next((tmp_path / ".paicli" / "refactor-agent" / "tasks").iterdir())
    issue_data = json.loads((task_dir / "issue.json").read_text(encoding="utf-8"))
    plan_data = json.loads((task_dir / "plan.json").read_text(encoding="utf-8"))
    issue_data.update({"auto_applicable": False, "requires_review": True})
    plan_data["requires_user_confirmation"] = True

    loaded_issue = RefactorIssue.from_dict(issue_data)
    loaded_plan = RefactorPlan.from_dict(plan_data)

    assert "auto_applicable" not in loaded_issue.to_dict()
    assert "requires_review" not in loaded_issue.to_dict()
    assert "requires_user_confirmation" not in loaded_plan.to_dict()


def test_apply_rejects_llm_patch_outside_plan_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = _write_java_file(tmp_path)
    issue = _dead_code_issue(source_path)
    _save_plan(tmp_path, issue, files_to_modify=["src/main/java/demo/Other.java"])
    task_dir = next((tmp_path / ".paicli" / "refactor-agent" / "tasks").iterdir())
    plan, _ = RefactorAgentStorage(tmp_path).load_task_plan(task_dir)

    with pytest.raises(PatchError, match="outside plan"):
        RefactorPatcher(tmp_path).generate_changes(
            plan,
            issue,
            llm_edit_plan={
                "edits": [
                    {
                        "file_path": issue.file_path,
                        "start_line": issue.start_line,
                        "end_line": issue.end_line,
                        "replacement": "",
                    }
                ]
            },
        )

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


def _dead_code_issue(
    source_path: Path,
    *,
    risk_level: RiskLevel = RiskLevel.LOW,
) -> RefactorIssue:
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
        risk_level=risk_level,
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
        risk_level=issue.risk_level,
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
    _write_jacoco_xml(tmp_path, issue.start_line)


def _write_jacoco_xml(root: Path, start_line: int) -> None:
    report_dir = root / "target" / "site" / "jacoco"
    report_dir.mkdir(parents=True, exist_ok=True)
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
        edit_arguments = {
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
        verification_calls = [
            *[
                ToolCall(
                    id=f"command-{index}",
                    function=_Function(
                        name="run_verification_command",
                        arguments=json.dumps({"command": command}),
                    ),
                )
                for index, command in enumerate(DEFAULT_VERIFICATION_COMMANDS, start=1)
            ],
            ToolCall(id="diff", function=_Function(name="inspect_diff", arguments="{}")),
            ToolCall(id="coverage", function=_Function(name="get_coverage_assessment", arguments="{}")),
        ]
        self.client = _ScriptedClient(
            [
                ChatResponse(
                    role="assistant",
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="apply",
                            function=_Function(name="apply_edits", arguments=json.dumps(edit_arguments)),
                        )
                    ],
                ),
                ChatResponse(
                    role="assistant",
                    content='{"status":"applied","summary":"done","changed_files":[],"risk_notes":[]}',
                ),
                ChatResponse(role="assistant", content="", tool_calls=verification_calls),
                ChatResponse(
                    role="assistant",
                    content=(
                        '{"approved":true,"status":"passed","summary":"verified",'
                        '"issues":[],"suggestions":[],"evidence_tools":["compile","test","coverage","diff"]}'
                    ),
                ),
            ]
        )


class _ScriptedClient:
    def __init__(self, responses: list[ChatResponse]) -> None:
        self.responses = responses

    async def chat(self, *, messages, tools=None) -> ChatResponse:
        del messages, tools
        return self.responses.pop(0)

    @property
    def max_context_window(self) -> int:
        return 128_000


def _successful_runner(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    del cwd
    return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")
