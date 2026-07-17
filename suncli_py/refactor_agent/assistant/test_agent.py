"""LLM-controlled pre-modification test generation agent."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from suncli_py.llm.client import LlmClient
from suncli_py.refactor_agent.assistant.prompts import test_generator_agent_system_prompt
from suncli_py.refactor_agent.assistant.react import AgentMessage, AgentRole, ReactAgent, ReactRunResult
from suncli_py.refactor_agent.assistant.toolbox import RefactorAgentToolbox, RefactorAgentToolRuntime
from suncli_py.refactor_agent.core.models import (
    CommandResult,
    CoverageAssessment,
    PreModificationResult,
    RefactorIssue,
    RefactorPlan,
)
from suncli_py.refactor_agent.execution.test_generator import (
    GeneratedTestApplication,
    GeneratedTestFileManager,
    TestGenerationError,
)
from suncli_py.refactor_agent.execution.verifier import (
    COVERAGE_COMMAND,
    JACOCO_TEST_COMMAND,
    TEST_COMMAND,
    TEST_COMPILE_COMMAND,
    CommandRunner,
    VerificationPipeline,
)


@dataclass(frozen=True)
class TestGeneratorOutcome:
    message: AgentMessage
    application: GeneratedTestApplication | None
    decision: dict[str, Any]
    react: ReactRunResult
    commands: list[CommandResult]
    coverage: CoverageAssessment
    infrastructure_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": self.message.to_dict(),
            "decision": self.decision,
            "test_files": self.application.test_files if self.application else [],
            "commands": [command.to_dict() for command in self.commands],
            "coverage": self.coverage.to_dict(),
            "infrastructure_error": self.infrastructure_error,
            "tool_trace": [trace.to_dict() for trace in self.react.traces],
            "input_tokens": self.react.input_tokens,
            "output_tokens": self.react.output_tokens,
        }


class TestGeneratorToolRuntime:
    def __init__(
        self,
        *,
        root: Path,
        plan: RefactorPlan,
        issue: RefactorIssue,
        task_dir: Path,
        preflight_dir: Path,
        command_runner: CommandRunner | None,
    ) -> None:
        self.root = root.resolve()
        self.plan = plan
        self.issue = issue
        self.toolbox = RefactorAgentToolbox(self.root)
        self.readonly = RefactorAgentToolRuntime(self.toolbox, plan=plan, issue=issue)
        self.files = GeneratedTestFileManager(self.root, issue, task_dir, preflight_dir)
        self.pipeline = VerificationPipeline(self.root, command_runner=command_runner)
        self.generation_version = 0
        self.prechecked_version = -1
        self.precheck_ok = False
        self.commands: list[CommandResult] = []
        self.coverage = plan.coverage_assessment
        self.infrastructure_error = ""

    def schemas(self) -> list[dict[str, Any]]:
        readonly = [
            schema
            for schema in self.readonly.schemas()
            if schema["function"]["name"]
            in {"get_issue_context", "read_file", "search_code", "get_plan_context"}
        ]
        return [
            *readonly,
            {
                "type": "function",
                "function": {
                    "name": "inspect_test_conventions",
                    "description": "Read representative existing Java tests and Maven build files.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "apply_test_edits",
                    "description": (
                        "Create or revise a complete set of new behavior-locking tests. Existing files and "
                        "production files cannot be overwritten."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "files": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "file_path": {"type": "string", "enum": self.files.allowed_files},
                                        "content": {"type": "string"},
                                    },
                                    "required": ["file_path", "content"],
                                },
                            }
                        },
                        "required": ["files"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "run_generated_test_precheck",
                    "description": (
                        "Compile generated tests, run the full test suite twice, run JaCoCo, and verify that "
                        "the target source file is covered."
                    ),
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
        ]

    def is_read_only(self, name: str) -> bool:
        return name not in {"apply_test_edits", "run_generated_test_precheck"}

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        if name in {"get_issue_context", "read_file", "search_code", "get_plan_context"}:
            return self.readonly.execute(name, arguments)
        if name == "inspect_test_conventions":
            return json.dumps(self._test_conventions(), ensure_ascii=False)
        if name == "apply_test_edits":
            try:
                application = self.files.apply(arguments.get("files"))
            except (TestGenerationError, OSError, ValueError) as err:
                return json.dumps({"ok": False, "error": str(err)}, ensure_ascii=False)
            self.generation_version += 1
            self.precheck_ok = False
            return json.dumps(
                {
                    "ok": True,
                    "generation_version": self.generation_version,
                    "test_files": application.test_files,
                    "patch_path": str(application.patch_path),
                },
                ensure_ascii=False,
            )
        if name == "run_generated_test_precheck":
            return self._run_precheck()
        return json.dumps({"error": f"unknown test-generator tool: {name}"}, ensure_ascii=False)

    def _test_conventions(self) -> dict[str, Any]:
        java_tests: list[str] = []
        for path in sorted(self.root.rglob("*.java")):
            relative = path.relative_to(self.root)
            if any(part in {".git", ".paicli", "target", "build"} for part in relative.parts):
                continue
            normalized = relative.as_posix()
            if "/src/test/java/" not in f"/{normalized}":
                continue
            java_tests.append(normalized)
            if len(java_tests) >= 6:
                break
        poms = []
        for path in sorted(self.root.rglob("pom.xml")):
            relative = path.relative_to(self.root)
            if "target" in relative.parts:
                continue
            poms.append(
                {
                    "file_path": relative.as_posix(),
                    "content": path.read_text(encoding="utf-8", errors="replace")[:5000],
                }
            )
            if len(poms) >= 3:
                break
        return {
            "existing_tests": [
                {"file_path": path, "content": self.toolbox.read_file(path, max_chars=5000)}
                for path in java_tests
            ],
            "maven_files": poms,
            "allowed_new_test_files": self.files.allowed_files,
        }

    def _run_precheck(self) -> str:
        if self.files.application is None:
            return json.dumps({"ok": False, "error": "apply_test_edits must succeed first"}, ensure_ascii=False)
        self.commands = [
            self.pipeline.run_command(TEST_COMPILE_COMMAND),
            self.pipeline.run_command(TEST_COMMAND),
            self.pipeline.run_command(JACOCO_TEST_COMMAND),
            self.pipeline.run_command(COVERAGE_COMMAND),
        ]
        infrastructure = next((command for command in self.commands if command.exit_code == 127), None)
        self.infrastructure_error = (
            f"Generated-test verification infrastructure failed: {infrastructure.command}: "
            f"{infrastructure.stderr or infrastructure.stdout}"
            if infrastructure is not None
            else ""
        )
        try:
            self.coverage = self.pipeline.coverage_assessment(self.plan, self.issue)
        except Exception as err:
            self.precheck_ok = False
            return json.dumps({"ok": False, "error": f"coverage assessment failed: {err}"}, ensure_ascii=False)
        self.prechecked_version = self.generation_version
        self.precheck_ok = bool(
            not self.infrastructure_error
            and all(command.exit_code == 0 for command in self.commands)
            and self.coverage.jacoco_report_found
            and self.coverage.target_file_lines_covered > 0
        )
        return json.dumps(
            {
                "ok": self.precheck_ok,
                "generation_version": self.generation_version,
                "commands": [command.to_dict() for command in self.commands],
                "coverage": self.coverage.to_dict(),
                "infrastructure_error": self.infrastructure_error,
                "error": "" if self.precheck_ok else "generated tests did not satisfy the mandatory precheck",
            },
            ensure_ascii=False,
        )

    def latest_version_passed(self) -> bool:
        return bool(
            self.files.application is not None
            and self.precheck_ok
            and self.prechecked_version == self.generation_version
        )


class TestGeneratorAgent:
    def __init__(self, client: LlmClient, root: Path) -> None:
        self.client = client
        self.root = root.resolve()

    def run(
        self,
        *,
        plan: RefactorPlan,
        issue: RefactorIssue,
        task_dir: Path,
        preflight_dir: Path,
        preflight: PreModificationResult,
        command_runner: CommandRunner | None,
    ) -> TestGeneratorOutcome:
        runtime = TestGeneratorToolRuntime(
            root=self.root,
            plan=plan,
            issue=issue,
            task_dir=task_dir,
            preflight_dir=preflight_dir,
            command_runner=command_runner,
        )
        react = ReactAgent(
            name="test-generator",
            client=self.client,
            root=self.root,
            system_prompt=test_generator_agent_system_prompt(),
            role=AgentRole.TEST_GENERATOR,
            tools=runtime,
        )
        task = {
            "issue": issue.to_dict(),
            "confirmed_plan": plan.to_dict(),
            "pre_modification_evidence": preflight.to_dict(),
            "allowed_new_test_files": runtime.files.allowed_files,
            "required_output": {
                "status": "created|cannot_generate",
                "summary": "string",
                "test_files": ["string"],
                "assertion_intents": ["string"],
                "risk_notes": ["string"],
            },
        }

        def validate(data: dict[str, Any]) -> str | None:
            if data.get("status") not in {"created", "cannot_generate"}:
                return "status must be created or cannot_generate."
            if not isinstance(data.get("summary"), str):
                return "summary must be a string."
            for field_name in ("test_files", "assertion_intents", "risk_notes"):
                if not isinstance(data.get(field_name), list):
                    return f"{field_name} must be an array."
            if data.get("status") == "created" and not runtime.latest_version_passed():
                return "status=created requires the latest generated tests to pass run_generated_test_precheck."
            return None

        result = react.run_json(json.dumps(task, ensure_ascii=False, indent=2), validator=validate)
        decision = result.data or {}
        if result.error:
            message = AgentMessage.error("test-generator", AgentRole.TEST_GENERATOR, result.error)
        elif decision.get("status") != "created" or not runtime.latest_version_passed():
            message = AgentMessage.error(
                "test-generator",
                AgentRole.TEST_GENERATOR,
                str(decision.get("summary") or "Could not generate a safe pre-refactor test."),
            )
        else:
            assert runtime.files.application is not None
            decision["test_files"] = list(runtime.files.application.test_files)
            message = AgentMessage.result(
                "test-generator",
                AgentRole.TEST_GENERATOR,
                json.dumps(decision, ensure_ascii=False),
            )
        return TestGeneratorOutcome(
            message=message,
            application=runtime.files.application if runtime.latest_version_passed() else None,
            decision=decision,
            react=result,
            commands=runtime.commands,
            coverage=runtime.coverage,
            infrastructure_error=runtime.infrastructure_error,
        )
