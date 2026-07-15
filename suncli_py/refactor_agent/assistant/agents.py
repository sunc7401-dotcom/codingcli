"""LLM-controlled modifier and verifier agents for the apply workflow."""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from suncli_py.llm.client import LlmClient
from suncli_py.refactor_agent.assistant.prompts import (
    modifier_agent_system_prompt,
    verifier_agent_system_prompt,
)
from suncli_py.refactor_agent.assistant.react import (
    AgentMessage,
    AgentRole,
    ReactAgent,
    ReactRunResult,
)
from suncli_py.refactor_agent.assistant.toolbox import RefactorAgentToolbox, RefactorAgentToolRuntime
from suncli_py.refactor_agent.core.models import CommandResult, RefactorIssue, RefactorPlan, VerificationResult
from suncli_py.refactor_agent.execution.patcher import (
    PatchApplicationResult,
    PatchError,
    RefactorPatcher,
)
from suncli_py.refactor_agent.execution.verifier import (
    COMPILE_COMMAND,
    COVERAGE_COMMAND,
    DEFAULT_VERIFICATION_COMMANDS,
    TEST_COMMAND,
    CommandRunner,
    VerificationPipeline,
)


@dataclass(frozen=True)
class ModifierOutcome:
    message: AgentMessage
    application: PatchApplicationResult | None
    decision: dict[str, Any]
    react: ReactRunResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": self.message.to_dict(),
            "decision": self.decision,
            "changed_files": self.application.changed_files if self.application else [],
            "tool_trace": [trace.to_dict() for trace in self.react.traces],
            "input_tokens": self.react.input_tokens,
            "output_tokens": self.react.output_tokens,
        }


@dataclass(frozen=True)
class VerifierOutcome:
    message: AgentMessage
    verification: VerificationResult | None
    decision: dict[str, Any]
    react: ReactRunResult
    infrastructure_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": self.message.to_dict(),
            "decision": self.decision,
            "verification": self.verification.to_dict() if self.verification else None,
            "infrastructure_error": self.infrastructure_error,
            "tool_trace": [trace.to_dict() for trace in self.react.traces],
            "input_tokens": self.react.input_tokens,
            "output_tokens": self.react.output_tokens,
        }


class ModifierToolRuntime:
    def __init__(
        self,
        *,
        root: Path,
        plan: RefactorPlan,
        issue: RefactorIssue,
        task_dir: Path,
        attempt_dir: Path,
        verification: VerificationResult | None,
    ) -> None:
        self.plan = plan
        self.issue = issue
        self.task_dir = task_dir
        self.attempt_dir = attempt_dir
        toolbox = RefactorAgentToolbox(root)
        self.readonly = RefactorAgentToolRuntime(
            toolbox,
            plan=plan,
            issue=issue,
            verification=verification,
        )
        self.patcher = RefactorPatcher(root)
        self.application: PatchApplicationResult | None = None

    def schemas(self) -> list[dict[str, Any]]:
        return [
            *self.readonly.schemas(),
            {
                "type": "function",
                "function": {
                    "name": "apply_edits",
                    "description": (
                        "Apply one complete set of controlled line edits. The runtime snapshots all planned files, "
                        "checks allowed paths and line ranges, writes files transactionally, and validates Java AST."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "edits": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "file_path": {"type": "string"},
                                        "start_line": {"type": "integer"},
                                        "end_line": {"type": "integer"},
                                        "replacement": {"type": "string"},
                                    },
                                    "required": ["file_path", "start_line", "end_line", "replacement"],
                                },
                            },
                            "explanation": {"type": "string"},
                        },
                        "required": ["edits", "explanation"],
                    },
                },
            },
        ]

    def is_read_only(self, name: str) -> bool:
        return name != "apply_edits" and self.readonly.is_read_only(name)

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        if name != "apply_edits":
            return self.readonly.execute(name, arguments)
        if self.application is not None:
            return json.dumps(
                {"ok": False, "error": "apply_edits already succeeded in this attempt"},
                ensure_ascii=False,
            )
        edits = arguments.get("edits")
        if not isinstance(edits, list) or not edits:
            return json.dumps({"ok": False, "error": "edits must be a non-empty array"}, ensure_ascii=False)
        edit_plan = {"edits": edits, "explanation": str(arguments.get("explanation") or "")}
        try:
            changes = self.patcher.generate_changes(self.plan, self.issue, llm_edit_plan=edit_plan)
            self.application = self.patcher.apply_changes(
                self.plan,
                changes,
                self.task_dir,
                artifact_dir=self.attempt_dir,
            )
        except (PatchError, OSError, ValueError) as err:
            return json.dumps({"ok": False, "error": str(err)}, ensure_ascii=False)
        return json.dumps(
            {
                "ok": True,
                "changed_files": self.application.changed_files,
                "patch_path": str(self.application.patch_path),
                "snapshot_path": str(self.application.snapshot_path),
                "diff": self.application.diff_text,
            },
            ensure_ascii=False,
        )


class ModifierAgent:
    def __init__(self, client: LlmClient, root: Path) -> None:
        self.root = root.resolve()
        self.react = ReactAgent(
            name="modifier",
            client=client,
            root=self.root,
            system_prompt=modifier_agent_system_prompt(),
            role=AgentRole.MODIFIER,
        )

    def run(
        self,
        *,
        plan: RefactorPlan,
        issue: RefactorIssue,
        task_dir: Path,
        attempt_dir: Path,
        attempt: int,
        verification: VerificationResult | None,
    ) -> ModifierOutcome:
        runtime = ModifierToolRuntime(
            root=self.root,
            plan=plan,
            issue=issue,
            task_dir=task_dir,
            attempt_dir=attempt_dir,
            verification=verification,
        )
        self.react.tools = runtime
        task = {
            "attempt": attempt,
            "issue": issue.to_dict(),
            "confirmed_plan": plan.to_dict(),
            "allowed_files": plan.files_to_modify,
            "verification_feedback": verification.to_dict() if verification else None,
            "required_output": {
                "status": "applied|cannot_apply",
                "summary": "string",
                "changed_files": ["string"],
                "risk_notes": ["string"],
            },
        }

        def validate(data: dict[str, Any]) -> str | None:
            status = data.get("status")
            if status not in {"applied", "cannot_apply"}:
                return "status must be applied or cannot_apply."
            if not isinstance(data.get("summary"), str):
                return "summary must be a string."
            if not isinstance(data.get("changed_files"), list):
                return "changed_files must be an array."
            if not isinstance(data.get("risk_notes"), list):
                return "risk_notes must be an array."
            if status == "applied" and runtime.application is None:
                return "status=applied requires a successful apply_edits tool call."
            return None

        result = self.react.run_json(json.dumps(task, ensure_ascii=False, indent=2), validator=validate)
        decision = result.data or {}
        if result.error:
            message = AgentMessage.error("modifier", AgentRole.MODIFIER, result.error)
        elif decision.get("status") != "applied" or runtime.application is None:
            message = AgentMessage.error(
                "modifier",
                AgentRole.MODIFIER,
                str(decision.get("summary") or "Modifier could not apply a safe change."),
            )
        else:
            decision["changed_files"] = list(runtime.application.changed_files)
            message = AgentMessage.result(
                "modifier",
                AgentRole.MODIFIER,
                json.dumps(decision, ensure_ascii=False),
            )
        return ModifierOutcome(message, runtime.application, decision, result)


class VerifierToolRuntime:
    def __init__(
        self,
        *,
        root: Path,
        plan: RefactorPlan,
        issue: RefactorIssue,
        task_dir: Path,
        command_runner: CommandRunner | None,
    ) -> None:
        self.plan = plan
        self.issue = issue
        self.task_dir = task_dir
        toolbox = RefactorAgentToolbox(root)
        self.readonly = RefactorAgentToolRuntime(toolbox, plan=plan, issue=issue)
        self.pipeline = VerificationPipeline(root, command_runner=command_runner)
        self.allowed_commands = _allowed_verification_commands(plan)
        self.command_results: dict[str, CommandResult] = {}
        self.diff_inspected = False
        self.coverage_assessed = False
        self.diff_summary = ""
        self.static_findings: list[str] = []

    def schemas(self) -> list[dict[str, Any]]:
        readonly = [
            schema
            for schema in self.readonly.schemas()
            if schema["function"]["name"] in {"read_file", "search_code", "get_plan_context"}
        ]
        return [
            *readonly,
            {
                "type": "function",
                "function": {
                    "name": "inspect_diff",
                    "description": "Read the applied patch and deterministic static diff findings.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "run_verification_command",
                    "description": "Run one registered Maven verification command without a shell.",
                    "parameters": {
                        "type": "object",
                        "properties": {"command": {"type": "string", "enum": self.allowed_commands}},
                        "required": ["command"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_coverage_assessment",
                    "description": "Assess changed-line coverage from the generated JaCoCo report.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
        ]

    def is_read_only(self, name: str) -> bool:
        return name != "run_verification_command"

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        if name in {"read_file", "search_code", "get_plan_context"}:
            return self.readonly.execute(name, arguments)
        if name == "inspect_diff":
            self.diff_inspected = True
            self.diff_summary, self.static_findings = self.pipeline.inspect_diff(self.plan, self.task_dir)
            return json.dumps(
                {"diff": self.diff_summary, "static_findings": self.static_findings},
                ensure_ascii=False,
            )
        if name == "run_verification_command":
            command = str(arguments.get("command") or "").strip()
            if command not in self.allowed_commands:
                return json.dumps({"error": "command is not registered", "command": command}, ensure_ascii=False)
            if command not in self.command_results:
                self.command_results[command] = self.pipeline.run_command(command)
            return json.dumps(self.command_results[command].to_dict(), ensure_ascii=False)
        if name == "get_coverage_assessment":
            self.coverage_assessed = True
            return json.dumps(self.pipeline.coverage_assessment(self.plan, self.issue).to_dict(), ensure_ascii=False)
        return json.dumps({"error": f"unknown verifier tool: {name}"}, ensure_ascii=False)

    def evidence_error(self) -> str | None:
        missing = [command for command in DEFAULT_VERIFICATION_COMMANDS if command not in self.command_results]
        if missing:
            return "Missing mandatory verification commands: " + ", ".join(missing)
        if not self.diff_inspected:
            return "inspect_diff must be called before the final decision."
        if not self.coverage_assessed:
            return "get_coverage_assessment must be called before the final decision."
        return None


class VerifierAgent:
    def __init__(self, client: LlmClient, root: Path) -> None:
        self.client = client
        self.root = root.resolve()

    def run(
        self,
        *,
        plan: RefactorPlan,
        issue: RefactorIssue,
        task_dir: Path,
        attempt: int,
        command_runner: CommandRunner | None,
    ) -> VerifierOutcome:
        runtime = VerifierToolRuntime(
            root=self.root,
            plan=plan,
            issue=issue,
            task_dir=task_dir,
            command_runner=command_runner,
        )
        react = ReactAgent(
            name="verifier",
            client=self.client,
            root=self.root,
            system_prompt=verifier_agent_system_prompt(),
            role=AgentRole.VERIFIER,
            tools=runtime,
        )
        task = {
            "attempt": attempt,
            "issue": issue.to_dict(),
            "confirmed_plan": plan.to_dict(),
            "required_commands": list(DEFAULT_VERIFICATION_COMMANDS),
            "required_output": {
                "approved": "boolean",
                "status": "passed|warning|failed",
                "summary": "string",
                "issues": ["string"],
                "suggestions": ["string"],
                "evidence_tools": ["string"],
            },
        }

        def validate(data: dict[str, Any]) -> str | None:
            evidence_error = runtime.evidence_error()
            if evidence_error:
                return evidence_error
            if not isinstance(data.get("approved"), bool):
                return "approved must be a boolean."
            if data.get("status") not in {"passed", "warning", "failed"}:
                return "status must be passed, warning, or failed."
            if not isinstance(data.get("summary"), str):
                return "summary must be a string."
            if data["approved"] and data["status"] == "failed":
                return "approved=true is inconsistent with status=failed."
            if not data["approved"] and data["status"] != "failed":
                return "approved=false requires status=failed."
            for field_name in ("issues", "suggestions", "evidence_tools"):
                if not isinstance(data.get(field_name), list):
                    return f"{field_name} must be an array."
            return None

        result = react.run_json(json.dumps(task, ensure_ascii=False, indent=2), validator=validate)
        decision = result.data or {}
        if result.error:
            message = AgentMessage.error("verifier", AgentRole.VERIFIER, result.error)
            try:
                coverage = runtime.pipeline.coverage_assessment(plan, issue)
            except Exception:
                coverage = plan.coverage_assessment
            try:
                diff_summary, static_findings = runtime.pipeline.inspect_diff(plan, task_dir)
            except Exception:
                diff_summary, static_findings = "", []
            verification = VerificationResult(
                status="failed",
                commands=list(runtime.command_results.values()),
                coverage=coverage,
                static_findings=static_findings,
                diff_summary=diff_summary,
                message=result.error,
                approved=False,
                decision_source="infrastructure",
                issues=[result.error],
                suggestions=[],
                attempt=attempt,
            )
            return VerifierOutcome(message, verification, decision, result, result.error)

        infrastructure = _infrastructure_error(runtime)
        hard_issues = _hard_verification_issues(runtime)
        model_issues = _string_items(decision.get("issues"))
        issues = [*model_issues, *[item for item in hard_issues if item not in model_issues]]
        if infrastructure and infrastructure not in issues:
            issues.append(infrastructure)
        approved = bool(decision.get("approved")) and not hard_issues and not infrastructure
        coverage = runtime.pipeline.coverage_assessment(plan, issue)
        if not runtime.diff_inspected:
            runtime.diff_summary, runtime.static_findings = runtime.pipeline.inspect_diff(plan, task_dir)
        has_warning = bool(
            runtime.command_results[COVERAGE_COMMAND].exit_code != 0
            or coverage.needs_characterization_test
            or runtime.static_findings
        )
        status = "failed" if not approved else "warning" if has_warning else "passed"
        summary = str(decision.get("summary") or "Verifier completed evidence review.")
        verification = VerificationResult(
            status=status,
            commands=list(runtime.command_results.values()),
            coverage=coverage,
            static_findings=runtime.static_findings,
            diff_summary=runtime.diff_summary,
            message=summary,
            approved=approved,
            decision_source="infrastructure" if infrastructure else "llm-verifier",
            issues=issues,
            suggestions=_string_items(decision.get("suggestions")),
            attempt=attempt,
        )
        if infrastructure:
            message = AgentMessage.error("verifier", AgentRole.VERIFIER, infrastructure)
        elif approved:
            message = AgentMessage.approval(json.dumps(verification.to_dict(), ensure_ascii=False))
        else:
            message = AgentMessage.rejection(json.dumps(verification.to_dict(), ensure_ascii=False))
        return VerifierOutcome(message, verification, decision, result, infrastructure)


def _allowed_verification_commands(plan: RefactorPlan) -> list[str]:
    commands = list(DEFAULT_VERIFICATION_COMMANDS)
    for command in plan.verification_commands:
        normalized = " ".join(command.strip().split())
        if normalized and normalized not in commands and _is_safe_maven_command(normalized):
            commands.append(normalized)
    return commands


def _is_safe_maven_command(command: str) -> bool:
    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    if not parts:
        return False
    executable = Path(parts[0].replace("\\", "/")).name.lower()
    if executable not in {"mvn", "mvn.cmd", "mvnw", "mvnw.cmd"}:
        return False
    lowered = command.lower()
    forbidden = ("|", ";", "&&", ">", "<", "exec:", "antrun:", " deploy", " install", " clean")
    return not any(marker in lowered for marker in forbidden)


def _hard_verification_issues(runtime: VerifierToolRuntime) -> list[str]:
    issues: list[str] = []
    for command in (COMPILE_COMMAND, TEST_COMMAND):
        result = runtime.command_results.get(command)
        if result is None:
            issues.append(f"Mandatory verification command was not run: {command}")
        elif result.exit_code != 0:
            output = (result.stderr or result.stdout or "command failed without output")[-1000:]
            issues.append(f"Verification command failed: {command}\n{output}")
    return issues


def _infrastructure_error(runtime: VerifierToolRuntime) -> str:
    failures = [result for result in runtime.command_results.values() if result.exit_code == 127]
    if not failures:
        return ""
    first = failures[0]
    return f"Verification infrastructure failed: {first.command}: {first.stderr or first.stdout}"


def _string_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
