from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from suncli_py.llm.models import ChatResponse, ToolCall, _Function
from suncli_py.refactor_agent.assistant.agents import (
    ModifierAgent,
    ModifierToolRuntime,
    VerifierAgent,
    VerifierToolRuntime,
)
from suncli_py.refactor_agent.assistant.orchestrator import RefactorAgentOrchestrator
from suncli_py.refactor_agent.assistant.react import AgentBudget, AgentExitReason, ReactAgent
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
from suncli_py.refactor_agent.execution.verifier import (
    DEFAULT_VERIFICATION_COMMANDS,
    VerificationPipeline,
)


def test_react_budget_detects_stagnation_and_hard_limit() -> None:
    call = ToolCall(id="1", function=_Function(name="read_file", arguments='{"file_path":"A.java"}'))
    budget = AgentBudget(token_budget=1000, stagnation_window=3, hard_max_iterations=50)
    for _ in range(3):
        budget.begin_iteration()
        budget.record_tool_calls([call])
    assert budget.check() == AgentExitReason.STAGNATION_DETECTED

    hard_limit = AgentBudget(token_budget=1000, stagnation_window=3, hard_max_iterations=2)
    hard_limit.begin_iteration()
    hard_limit.begin_iteration()
    assert hard_limit.check() == AgentExitReason.HARD_ITERATION_LIMIT

    token_limit = AgentBudget(token_budget=10, stagnation_window=3, hard_max_iterations=50)
    token_limit.record_tokens(6, 4)
    assert token_limit.check() == AgentExitReason.TOKEN_BUDGET_EXCEEDED


def test_react_rejects_invalid_json_then_self_corrects(tmp_path: Path) -> None:
    client = _ScriptedClient(
        [
            ChatResponse(role="assistant", content="not json"),
            ChatResponse(role="assistant", content='{"status":"ok"}'),
        ]
    )
    result = ReactAgent(name="test", client=client, root=tmp_path, system_prompt="return json").run_json("task")
    assert result.data == {"status": "ok"}
    assert any("rejected by the runtime" in message.content for message in client.seen_messages)


def test_react_uses_history_compression_and_returns_llm_errors(tmp_path: Path) -> None:
    memory = _TrackingMemory()
    result = ReactAgent(
        name="test",
        client=_ScriptedClient([ChatResponse(role="assistant", content='{"status":"ok"}')]),
        root=tmp_path,
        system_prompt="return json",
        memory=memory,
    ).run_json("task")
    assert result.succeeded is True
    assert memory.compactions == 1

    failed = ReactAgent(
        name="test",
        client=_ExplodingClient(),
        root=tmp_path,
        system_prompt="return json",
    ).run_json("task")
    assert failed.succeeded is False
    assert "LLM request failed: provider unavailable" in failed.error


def test_modifier_and_verifier_agents_apply_and_record_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, issue, plan, task_dir = _project(tmp_path)
    monkeypatch.setattr(AstPatchValidator, "validate", lambda self, plan, task_dir: [])
    client = _ScriptedClient(
        [
            _modifier_tool(issue, ""),
            _modifier_final(),
            _verifier_final(approved=True),
            _verification_tools(),
            _verifier_final(approved=True),
        ]
    )
    storage = RefactorAgentStorage(tmp_path)
    result = RefactorAgentOrchestrator(
        root=tmp_path,
        client=client,
        storage=storage,
        command_runner=_successful_runner,
    ).run(plan=plan, issue=issue, task_dir=task_dir, max_repair_attempts=0)

    assert result.success is True
    assert result.verification is not None and result.verification.approved is True
    assert "unusedPrivate" not in source.read_text(encoding="utf-8")
    attempt_dir = task_dir / "attempts" / "01"
    assert (attempt_dir / "modifier.json").is_file()
    assert (attempt_dir / "patch.diff").is_file()
    assert (attempt_dir / "verification.json").is_file()
    assert not (attempt_dir / "feedback.json").exists()
    assert (task_dir / "agent_messages.jsonl").is_file()
    message_types = [
        json.loads(line)["type"]
        for line in (task_dir / "agent_messages.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert message_types == ["TASK", "RESULT", "TASK", "APPROVAL"]
    assert any("Missing mandatory verification commands" in message.content for message in client.seen_messages)


def test_modifier_cannot_claim_success_without_apply_tool(tmp_path: Path) -> None:
    _, issue, plan, task_dir = _project(tmp_path)
    client = _ScriptedClient(
        [
            _modifier_final(),
            ChatResponse(
                role="assistant",
                content=(
                    '{"status":"cannot_apply","summary":"no safe edit",'
                    '"changed_files":[],"risk_notes":[]}'
                ),
            ),
        ]
    )

    outcome = ModifierAgent(client, tmp_path).run(
        plan=plan,
        issue=issue,
        task_dir=task_dir,
        attempt_dir=task_dir / "attempts" / "01",
        attempt=1,
        verification=None,
    )

    assert outcome.application is None
    assert outcome.message.type.value == "ERROR"
    assert any("requires a successful apply_edits" in message.content for message in client.seen_messages)


def test_verifier_rejects_unregistered_commands_and_classifies_timeout(tmp_path: Path) -> None:
    _, issue, plan, task_dir = _project(tmp_path)
    runtime = VerifierToolRuntime(
        root=tmp_path,
        plan=plan,
        issue=issue,
        task_dir=task_dir,
        command_runner=_successful_runner,
    )
    illegal = json.loads(
        runtime.execute("run_verification_command", {"command": "mvn test && rm -rf target"})
    )
    assert illegal["error"] == "command is not registered"

    def timeout_runner(command, cwd):
        del cwd
        raise subprocess.TimeoutExpired(command, timeout=1)

    timed_out = VerificationPipeline(tmp_path, command_runner=timeout_runner).run_command(
        DEFAULT_VERIFICATION_COMMANDS[0]
    )
    assert timed_out.exit_code == 127
    assert "timed out" in timed_out.stderr


def test_verifier_cannot_approve_real_workspace_changes_outside_plan(tmp_path: Path) -> None:
    source, issue, plan, task_dir = _project(tmp_path)
    RefactorPatcher(tmp_path).ensure_initial_snapshot(plan, task_dir)
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "    private int unusedPrivate(int value) {\n        return value * 2;\n    }\n",
            "",
        ),
        encoding="utf-8",
    )
    (tmp_path / "pom.xml").write_text("<project />", encoding="utf-8")
    client = _ScriptedClient([_verification_tools(), _verifier_final(approved=True)])

    outcome = VerifierAgent(client, tmp_path).run(
        plan=plan,
        issue=issue,
        task_dir=task_dir,
        attempt=1,
        command_runner=_successful_runner,
    )

    assert outcome.verification is not None
    assert outcome.verification.approved is False
    assert outcome.verification.status == "failed"
    assert "任务开始后出现计划外工作区变化: pom.xml" in outcome.verification.issues


def test_verifier_rejection_is_fed_back_to_modifier_before_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, issue, plan, task_dir = _project(tmp_path)
    original = source.read_text(encoding="utf-8")
    monkeypatch.setattr(AstPatchValidator, "validate", lambda self, plan, task_dir: [])
    return_line = next(
        index
        for index, line in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1)
        if "return input + 1" in line
    )
    client = _ScriptedClient(
        [
            _modifier_tool_for_line(issue.file_path, return_line, "        return missingSymbol;"),
            _modifier_final(),
            _verification_tools(),
            _verifier_final(approved=True),
            _modifier_tool(issue, ""),
            _modifier_final(),
            _verification_tools(),
            _verifier_final(approved=True),
        ]
    )
    runner = _FailCompileOnceRunner()
    result = RefactorAgentOrchestrator(
        root=tmp_path,
        client=client,
        storage=RefactorAgentStorage(tmp_path),
        command_runner=runner,
    ).run(plan=plan, issue=issue, task_dir=task_dir, max_repair_attempts=1)

    assert result.success is True
    assert result.attempts == 2
    assert "unusedPrivate" not in source.read_text(encoding="utf-8")
    assert "missingSymbol" not in source.read_text(encoding="utf-8")
    assert (task_dir / "attempts" / "01" / "feedback.json").is_file()
    snapshot = json.loads((task_dir / "snapshot.json").read_text(encoding="utf-8"))
    assert all("after_sha256" not in file_entry for file_entry in snapshot["files"])
    before_copy = task_dir / snapshot["files"][0]["before_copy"]
    assert before_copy.read_text(encoding="utf-8") == original
    assert (task_dir / "after_state.json").is_file()
    second_modifier = json.loads((task_dir / "attempts" / "02" / "modifier.json").read_text(encoding="utf-8"))
    assert second_modifier["message"]["type"] == "RESULT"
    modifier_second_task = [
        message.content
        for request in client.all_requests
        for message in request
        if message.role == "user" and '"attempt": 2' in message.content
    ]
    assert modifier_second_task and "Verification command failed" in modifier_second_task[0]


def test_repair_exhaustion_restores_immutable_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, issue, plan, task_dir = _project(tmp_path)
    original = source.read_text(encoding="utf-8")
    monkeypatch.setattr(AstPatchValidator, "validate", lambda self, plan, task_dir: [])
    client = _ScriptedClient(
        [
            _modifier_tool(issue, ""),
            _modifier_final(),
            _verification_tools(),
            _verifier_final(approved=False),
        ]
    )
    result = RefactorAgentOrchestrator(
        root=tmp_path,
        client=client,
        storage=RefactorAgentStorage(tmp_path),
        command_runner=_successful_runner,
    ).run(plan=plan, issue=issue, task_dir=task_dir, max_repair_attempts=0)

    assert result.success is False
    assert result.rollback is not None and result.rollback.status == "rolled_back"
    assert source.read_text(encoding="utf-8") == original
    assert (task_dir / "attempts" / "01" / "feedback.json").is_file()
    assert (task_dir / "patch.diff").is_file()


def test_modifier_tool_restores_file_when_ast_validation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, issue, plan, task_dir = _project(tmp_path)
    original = source.read_text(encoding="utf-8")
    monkeypatch.setattr(
        AstPatchValidator,
        "validate",
        lambda self, plan, task_dir: ["public API changed"],
    )
    runtime = ModifierToolRuntime(
        root=tmp_path,
        plan=plan,
        issue=issue,
        task_dir=task_dir,
        attempt_dir=task_dir / "attempts" / "01",
        verification=None,
    )

    result = json.loads(
        runtime.execute(
            "apply_edits",
            {
                "edits": [
                    {
                        "file_path": issue.file_path,
                        "start_line": issue.start_line,
                        "end_line": issue.end_line,
                        "replacement": "",
                    }
                ],
                "explanation": "remove method",
            },
        )
    )

    assert result["ok"] is False
    assert "AST patch validation failed" in result["error"]
    assert runtime.application is None
    assert source.read_text(encoding="utf-8") == original


def test_verification_infrastructure_error_rolls_back_without_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, issue, plan, task_dir = _project(tmp_path)
    original = source.read_text(encoding="utf-8")
    monkeypatch.setattr(AstPatchValidator, "validate", lambda self, plan, task_dir: [])
    client = _ScriptedClient(
        [
            _modifier_tool(issue, ""),
            _modifier_final(),
            _verification_tools(),
            _verifier_final(approved=True),
        ]
    )

    result = RefactorAgentOrchestrator(
        root=tmp_path,
        client=client,
        storage=RefactorAgentStorage(tmp_path),
        command_runner=_MissingMavenRunner(),
    ).run(plan=plan, issue=issue, task_dir=task_dir, max_repair_attempts=2)

    assert result.success is False
    assert result.attempts == 0
    assert "修改前验证基础设施不可用" in result.error
    assert result.rollback is not None and result.rollback.status == "rolled_back"
    assert source.read_text(encoding="utf-8") == original
    assert not (task_dir / "attempts").exists()
    preflight = json.loads((task_dir / "pre_modification.json").read_text(encoding="utf-8"))
    assert preflight["status"] == "infrastructure_error"


class _ScriptedClient:
    def __init__(self, responses: list[ChatResponse]) -> None:
        self.responses = list(responses)
        self.seen_messages = []
        self.all_requests = []

    async def chat(self, *, messages, tools=None) -> ChatResponse:
        del tools
        self.seen_messages = list(messages)
        self.all_requests.append(list(messages))
        if not self.responses:
            raise AssertionError("No scripted response remains")
        return self.responses.pop(0)

    @property
    def max_context_window(self) -> int:
        return 128_000


class _ExplodingClient:
    async def chat(self, *, messages, tools=None) -> ChatResponse:
        del messages, tools
        raise ValueError("provider unavailable")

    @property
    def max_context_window(self) -> int:
        return 128_000


class _TrackingMemory:
    def __init__(self) -> None:
        self.compactions = 0

    def prompt_context(self, query: str) -> str:
        del query
        return ""

    def add_user_message(self, content: str) -> None:
        del content

    def add_tool_result(self, tool_name: str, result: str) -> None:
        del tool_name, result

    def add_assistant_message(self, content: str) -> None:
        del content

    async def compact_history_if_needed(self, history) -> bool:
        del history
        self.compactions += 1
        return False


def _modifier_tool(issue: RefactorIssue, replacement: str) -> ChatResponse:
    return _modifier_tool_for_line(issue.file_path, issue.start_line, replacement, issue.end_line)


def _modifier_tool_for_line(
    file_path: str,
    start_line: int,
    replacement: str,
    end_line: int | None = None,
) -> ChatResponse:
    arguments = {
        "edits": [
            {
                "file_path": file_path,
                "start_line": start_line,
                "end_line": end_line or start_line,
                "replacement": replacement,
            }
        ],
        "explanation": "controlled edit",
    }
    return ChatResponse(
        role="assistant",
        content="",
        tool_calls=[ToolCall(id="apply", function=_Function(name="apply_edits", arguments=json.dumps(arguments)))],
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


def _verifier_final(*, approved: bool) -> ChatResponse:
    value = {
        "approved": approved,
        "status": "passed" if approved else "failed",
        "summary": "verified" if approved else "needs repair",
        "issues": [] if approved else ["verification rejected the patch"],
        "suggestions": [] if approved else ["revise the implementation"],
        "evidence_tools": ["inspect_diff", "compile", "test", "coverage"],
    }
    return ChatResponse(role="assistant", content=json.dumps(value))


def _successful_runner(command, cwd):
    del cwd
    return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")


class _FailCompileOnceRunner:
    def __init__(self) -> None:
        self.failed = False

    def __call__(self, command, cwd):
        source = cwd / "src" / "main" / "java" / "demo" / "OrderService.java"
        has_bad_edit = source.is_file() and "missingSymbol" in source.read_text(encoding="utf-8")
        if command[-1] == "compile" and has_bad_edit and not self.failed:
            self.failed = True
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="missingSymbol")
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")


class _MissingMavenRunner:
    def __call__(self, command, cwd):
        del cwd
        if command[-1] == "compile":
            return subprocess.CompletedProcess(command, 127, stdout="", stderr="mvn not found")
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")


def _project(tmp_path: Path) -> tuple[Path, RefactorIssue, RefactorPlan, Path]:
    source = tmp_path / "src" / "main" / "java" / "demo" / "OrderService.java"
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
    issue = RefactorIssue(
        id="RA-0001",
        type=SmellType.DEAD_CODE,
        severity=Severity.LOW,
        file_path=source.relative_to(tmp_path).as_posix(),
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
        task_id="ra-0001-test",
        issue_id=issue.id,
        goal="remove unused private method",
        refactoring_type=RefactoringType.REMOVE_DEAD_CODE,
        files_to_modify=[issue.file_path],
        expected_changes=["remove unusedPrivate"],
        out_of_scope=["public API"],
        risk_level=RiskLevel.LOW,
        risk_reasons=[],
        verification_commands=list(DEFAULT_VERIFICATION_COMMANDS[:2]),
        rollback_strategy="restore snapshot",
        coverage_assessment=CoverageAssessment(
            has_related_test_class=False,
            related_tests=[],
            confidence="low",
            needs_characterization_test=False,
            recommendation="run tests",
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
    storage = RefactorAgentStorage(tmp_path)
    storage.save_plan(plan, issue)
    _write_jacoco_xml(tmp_path, issue.start_line)
    return source, issue, plan, storage.task_dir(plan.task_id)


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
