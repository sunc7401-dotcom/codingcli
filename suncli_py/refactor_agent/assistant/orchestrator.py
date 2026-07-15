"""Preflight, test-generator, modifier, and verifier orchestration for apply."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

from suncli_py.llm.client import LlmClient
from suncli_py.refactor_agent.assistant.agents import ModifierAgent, VerifierAgent
from suncli_py.refactor_agent.assistant.react import AgentMessage, AgentMessageType
from suncli_py.refactor_agent.assistant.test_agent import TestGeneratorAgent
from suncli_py.refactor_agent.core.models import (
    PreModificationResult,
    RefactorIssue,
    RefactorPlan,
    RollbackResult,
    VerificationResult,
)
from suncli_py.refactor_agent.core.storage import RefactorAgentStorage
from suncli_py.refactor_agent.execution.patcher import PatchError, RefactorPatcher
from suncli_py.refactor_agent.execution.rollback import RollbackError, TaskRollbacker
from suncli_py.refactor_agent.execution.verifier import CommandRunner, PreModificationVerifier


@dataclass(frozen=True)
class ApplyWorkflowResult:
    success: bool
    verification: VerificationResult | None
    rollback: RollbackResult | None
    attempts: int
    changed_files: list[str] = field(default_factory=list)
    error: str = ""
    pre_modification: PreModificationResult | None = None
    generated_tests: list[str] = field(default_factory=list)


class RefactorAgentOrchestrator:
    """Run the safe serial workflow with bounded verifier-to-modifier feedback."""

    def __init__(
        self,
        *,
        root: Path,
        client: LlmClient,
        storage: RefactorAgentStorage,
        command_runner: CommandRunner | None = None,
    ) -> None:
        self.root = root.resolve()
        self.storage = storage
        self.command_runner = command_runner
        self.modifier = ModifierAgent(client, self.root)
        self.verifier = VerifierAgent(client, self.root)
        self.test_generator = TestGeneratorAgent(client, self.root)
        self.preflight = PreModificationVerifier(self.root, command_runner=command_runner)
        self.rollbacker = TaskRollbacker(self.root)

    def run(
        self,
        *,
        plan: RefactorPlan,
        issue: RefactorIssue,
        task_dir: Path,
        max_repair_attempts: int,
    ) -> ApplyWorkflowResult:
        try:
            RefactorPatcher(self.root).ensure_initial_snapshot(plan, task_dir)
        except (PatchError, OSError, ValueError) as err:
            return ApplyWorkflowResult(
                success=False,
                verification=None,
                rollback=None,
                attempts=0,
                error=f"Failed to create immutable initial snapshot: {err}",
            )

        preflight_dir = task_dir / "preflight"
        preflight_dir.mkdir(parents=True, exist_ok=True)
        pre_modification = self.preflight.verify(plan, issue)
        self.storage.save_pre_modification(task_dir, pre_modification, preflight_dir=preflight_dir)
        if pre_modification.status not in {"ready", "coverage_gap"}:
            rollback = self._final_rollback(task_dir)
            return ApplyWorkflowResult(
                success=False,
                verification=None,
                rollback=rollback,
                attempts=0,
                error=pre_modification.message,
                pre_modification=pre_modification,
            )

        effective_plan = plan
        generated_tests: list[str] = []
        generated_test_diff = ""
        if pre_modification.requires_test_generation:
            self._record_message(
                task_dir,
                0,
                AgentMessage.task(json.dumps({"target": "test-generator", "stage": "pre-modification"})),
            )
            generated = self.test_generator.run(
                plan=plan,
                issue=issue,
                task_dir=task_dir,
                preflight_dir=preflight_dir,
                preflight=pre_modification,
                command_runner=self.command_runner,
            )
            self.storage.save_attempt_record(preflight_dir, "test_generator.json", generated.to_dict())
            self._record_message(task_dir, 0, generated.message)
            if generated.application is None or generated.message.type == AgentMessageType.ERROR:
                rollback = self._final_rollback(task_dir)
                error = generated.infrastructure_error or generated.message.content
                return ApplyWorkflowResult(
                    success=False,
                    verification=None,
                    rollback=rollback,
                    attempts=0,
                    error=error,
                    pre_modification=pre_modification,
                )

            generated_tests = list(generated.application.test_files)
            generated_test_diff = generated.application.diff_text
            related_tests = list(dict.fromkeys([*plan.coverage_assessment.related_tests, *generated_tests]))
            effective_coverage = replace(
                generated.coverage,
                has_related_test_class=True,
                related_tests=related_tests,
                needs_characterization_test=False,
                generated_tests=generated_tests,
                recommendation="修改前生成的行为锁定测试已在原始代码上编译、连续通过两次并产生目标文件覆盖。",
            )
            effective_plan = replace(plan, coverage_assessment=effective_coverage)
            pre_modification = replace(
                pre_modification,
                status="ready_with_generated_tests",
                coverage=effective_coverage,
                requires_test_generation=False,
                message="修改前测试已生成并在原始代码上完成强制预检。",
                generated_tests=generated_tests,
            )
            self.storage.save_pre_modification(task_dir, pre_modification, preflight_dir=preflight_dir)
            self.storage.save_attempt_record(preflight_dir, "effective_plan.json", effective_plan.to_dict())

        total_attempts = max(0, max_repair_attempts) + 1
        previous_verification: VerificationResult | None = None
        last_changed_files: list[str] = list(generated_tests)

        for attempt in range(1, total_attempts + 1):
            attempt_dir = self.storage.attempt_dir(task_dir, attempt)
            if attempt > 1:
                recovery = self._rollback_if_possible(task_dir, preserve_generated_tests=True)
                if recovery is None or recovery.status != "rolled_back":
                    return ApplyWorkflowResult(
                        success=False,
                        verification=previous_verification,
                        rollback=recovery,
                        attempts=attempt - 1,
                        changed_files=last_changed_files,
                        error="Failed to restore production files while preserving generated tests before repair.",
                        pre_modification=pre_modification,
                        generated_tests=generated_tests,
                    )
                self.storage.save_attempt_record(attempt_dir, "pre_repair_rollback.json", recovery.to_dict())

            guard_error = self._generated_guard_error(task_dir)
            if guard_error:
                rollback = self._final_rollback(task_dir)
                return ApplyWorkflowResult(
                    success=False,
                    verification=previous_verification,
                    rollback=rollback,
                    attempts=attempt - 1,
                    changed_files=last_changed_files,
                    error=guard_error,
                    pre_modification=pre_modification,
                    generated_tests=generated_tests,
                )

            self._record_message(
                task_dir,
                attempt,
                AgentMessage.task(
                    json.dumps(
                        {"target": "modifier", "attempt": attempt, "has_feedback": previous_verification is not None}
                    )
                ),
            )
            modifier = self.modifier.run(
                plan=effective_plan,
                issue=issue,
                task_dir=task_dir,
                attempt_dir=attempt_dir,
                attempt=attempt,
                verification=previous_verification,
            )
            self.storage.save_attempt_record(attempt_dir, "modifier.json", modifier.to_dict())
            self._record_message(task_dir, attempt, modifier.message)
            if modifier.application is None or modifier.message.type == AgentMessageType.ERROR:
                rollback = self._final_rollback(task_dir)
                return ApplyWorkflowResult(
                    success=False,
                    verification=previous_verification,
                    rollback=rollback,
                    attempts=attempt,
                    changed_files=last_changed_files,
                    error=modifier.message.content,
                    pre_modification=pre_modification,
                    generated_tests=generated_tests,
                )

            last_changed_files = [*generated_tests, *modifier.application.changed_files]
            guard_error = self._generated_guard_error(task_dir)
            if guard_error:
                rollback = self._final_rollback(task_dir)
                return ApplyWorkflowResult(
                    success=False,
                    verification=previous_verification,
                    rollback=rollback,
                    attempts=attempt,
                    changed_files=last_changed_files,
                    error=guard_error,
                    pre_modification=pre_modification,
                    generated_tests=generated_tests,
                )
            self._publish_combined_diff(task_dir, generated_test_diff, modifier.application.diff_text)
            self._record_message(
                task_dir,
                attempt,
                AgentMessage.task(json.dumps({"target": "verifier", "attempt": attempt})),
            )
            verifier = self.verifier.run(
                plan=effective_plan,
                issue=issue,
                task_dir=task_dir,
                attempt=attempt,
                command_runner=self.command_runner,
            )
            self.storage.save_attempt_record(attempt_dir, "verifier.json", verifier.to_dict())
            self._record_message(task_dir, attempt, verifier.message)
            guard_error = self._generated_guard_error(task_dir)
            if guard_error:
                rollback = self._final_rollback(task_dir)
                return ApplyWorkflowResult(
                    success=False,
                    verification=previous_verification,
                    rollback=rollback,
                    attempts=attempt,
                    changed_files=last_changed_files,
                    error=guard_error,
                    pre_modification=pre_modification,
                    generated_tests=generated_tests,
                )
            if verifier.verification is not None:
                previous_verification = verifier.verification
                self.storage.save_verification(task_dir, verifier.verification, attempt_dir=attempt_dir)

            if verifier.infrastructure_error or verifier.verification is None:
                rollback = self._final_rollback(task_dir)
                return ApplyWorkflowResult(
                    success=False,
                    verification=previous_verification,
                    rollback=rollback,
                    attempts=attempt,
                    changed_files=last_changed_files,
                    error=verifier.infrastructure_error or verifier.message.content,
                    pre_modification=pre_modification,
                    generated_tests=generated_tests,
                )

            if verifier.verification.approved:
                return ApplyWorkflowResult(
                    success=True,
                    verification=verifier.verification,
                    rollback=None,
                    attempts=attempt,
                    changed_files=last_changed_files,
                    pre_modification=pre_modification,
                    generated_tests=generated_tests,
                )

            feedback = AgentMessage.feedback(verifier.message.content)
            self.storage.save_attempt_record(attempt_dir, "feedback.json", feedback.to_dict())
            self._record_message(task_dir, attempt, feedback)
            if attempt == total_attempts:
                rollback = self._final_rollback(task_dir)
                return ApplyWorkflowResult(
                    success=False,
                    verification=verifier.verification,
                    rollback=rollback,
                    attempts=attempt,
                    changed_files=last_changed_files,
                    error=verifier.verification.message,
                    pre_modification=pre_modification,
                    generated_tests=generated_tests,
                )

        return ApplyWorkflowResult(
            success=False,
            verification=previous_verification,
            rollback=None,
            attempts=total_attempts,
            changed_files=last_changed_files,
            pre_modification=pre_modification,
            generated_tests=generated_tests,
        )

    def _record_message(self, task_dir: Path, attempt: int, message: AgentMessage) -> None:
        self.storage.append_agent_message(task_dir, {"attempt": attempt, **message.to_dict()})

    def _generated_guard_error(self, task_dir: Path) -> str:
        try:
            conflicts = self.rollbacker.generated_test_conflicts(task_dir)
        except RollbackError as err:
            return f"Generated test guard state is invalid: {err}"
        if not conflicts:
            return ""
        return "Generated test guards changed unexpectedly: " + ", ".join(conflicts)

    def _publish_combined_diff(self, task_dir: Path, test_diff: str, production_diff: str) -> None:
        combined = "\n".join(part.rstrip() for part in (test_diff, production_diff) if part.strip()) + "\n"
        (task_dir / "patch.diff").write_text(combined, encoding="utf-8")
        (task_dir / "diff_summary.txt").write_text(combined, encoding="utf-8")

    def _rollback_if_possible(
        self,
        task_dir: Path,
        *,
        preserve_generated_tests: bool = False,
    ) -> RollbackResult | None:
        if not (task_dir / "snapshot.json").is_file():
            return None
        try:
            return self.rollbacker.rollback(
                task_dir,
                force=True,
                preserve_generated_tests=preserve_generated_tests,
            )
        except RollbackError:
            return None

    def _final_rollback(self, task_dir: Path) -> RollbackResult | None:
        result = self._rollback_if_possible(task_dir, preserve_generated_tests=False)
        if result is not None:
            self.storage.save_rollback(task_dir, result)
        return result
