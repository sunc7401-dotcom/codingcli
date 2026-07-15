"""Refactor-agent evidence chain report generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from suncli_py.refactor_agent.core.models import (
    CharacterizationTestPlan,
    RefactorIssue,
    RefactorPlan,
    RollbackResult,
    VerificationResult,
)


class ReportGenerator:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.base_dir = self.root / ".paicli" / "refactor-agent"

    def generate(
        self,
        task_dir: Path,
        plan: RefactorPlan,
        issue: RefactorIssue,
        verification: VerificationResult | None,
        rollback: RollbackResult | None,
        characterization: CharacterizationTestPlan | None = None,
    ) -> Path:
        task_report = task_dir / "report.md"
        text = self._format_report(task_dir, plan, issue, verification, rollback, characterization)
        task_report.write_text(text, encoding="utf-8")
        latest_dir = self.base_dir / "reports"
        latest_dir.mkdir(parents=True, exist_ok=True)
        (latest_dir / "latest.md").write_text(text, encoding="utf-8")
        return task_report

    def _format_report(
        self,
        task_dir: Path,
        plan: RefactorPlan,
        issue: RefactorIssue,
        verification: VerificationResult | None,
        rollback: RollbackResult | None,
        characterization: CharacterizationTestPlan | None,
    ) -> str:
        snapshot = _load_json(task_dir / "snapshot.json")
        pre_modification = _load_json(task_dir / "pre_modification.json")
        test_generator = _load_json(task_dir / "preflight" / "test_generator.json")
        diff_text = _read_text(task_dir / "diff_summary.txt")
        lines = [
            f"# Refactor Report {plan.task_id}",
            "",
            "## Risk",
            f"- Issue: {issue.id}",
            f"- Type: {issue.type}",
            f"- Risk: {plan.risk_level}",
            *[f"- {reason}" for reason in plan.risk_reasons],
            "",
            "## Plan",
            f"- Goal: {plan.goal}",
            f"- Refactoring: {plan.refactoring_type}",
            f"- Files: {', '.join(plan.files_to_modify)}",
            "",
            "## Snapshot",
            f"- Head: {snapshot.get('head') if snapshot else 'not recorded'}",
            f"- User changes before task: {snapshot.get('user_changes_before_task') if snapshot else 'unknown'}",
            "",
            "## Diff",
            "```diff",
            diff_text.rstrip() or "not recorded",
            "```",
            "",
            "## Pre-modification Baseline",
            *_format_pre_modification(pre_modification, test_generator),
            "",
            "## Agent Workflow",
            *_format_attempts(task_dir),
            "",
            "## Verification",
        ]
        if verification:
            lines.extend(
                [
                    f"- Status: {verification.status}",
                    f"- Approved: {verification.approved}",
                    f"- Decision source: {verification.decision_source}",
                    f"- Attempt: {verification.attempt}",
                    f"- Message: {verification.message}",
                    f"- Coverage confidence: {verification.coverage.confidence}",
                    f"- JaCoCo report found: {verification.coverage.jacoco_report_found}",
                    f"- Changed lines covered: "
                    f"{verification.coverage.changed_lines_covered}/{verification.coverage.changed_lines_total}",
                    f"- Coverage ratio: {verification.coverage.coverage_ratio}",
                ]
            )
            lines.append("- Commands:")
            lines.extend(f"  - `{command.command}` => {command.exit_code}" for command in verification.commands)
            if verification.issues:
                lines.append("- Issues:")
                lines.extend(f"  - {issue}" for issue in verification.issues)
            if verification.suggestions:
                lines.append("- Suggestions:")
                lines.extend(f"  - {suggestion}" for suggestion in verification.suggestions)
        else:
            lines.append("- Status: not run")

        lines.extend(["", "## Characterization"])
        if characterization:
            lines.extend(
                [
                    f"- Destination: {characterization.destination_file}",
                    f"- User confirmed: {characterization.user_confirmed}",
                    f"- Usable as guard: {characterization.usable_as_refactor_guard}",
                ]
            )
        else:
            lines.append("- Not generated")

        lines.extend(["", "## Rollback"])
        if rollback:
            lines.extend(
                [
                    f"- Status: {rollback.status}",
                    f"- Restored files: {', '.join(rollback.restored_files) or 'none'}",
                    f"- Conflicts: {', '.join(rollback.conflicts) or 'none'}",
                ]
            )
        else:
            lines.append("- Not rolled back")
        lines.append("")
        return "\n".join(lines)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _format_attempts(task_dir: Path) -> list[str]:
    attempts_dir = task_dir / "attempts"
    if not attempts_dir.is_dir():
        return ["- No modifier/verifier attempts recorded"]
    lines: list[str] = []
    for attempt_dir in sorted(path for path in attempts_dir.iterdir() if path.is_dir()):
        modifier = _load_json(attempt_dir / "modifier.json")
        verifier = _load_json(attempt_dir / "verifier.json")
        feedback = _load_json(attempt_dir / "feedback.json")
        modifier_type = modifier.get("message", {}).get("type", "not recorded")
        verifier_type = verifier.get("message", {}).get("type", "not recorded")
        lines.append(f"- Attempt {attempt_dir.name}: modifier={modifier_type}, verifier={verifier_type}")
        modifier_decision = modifier.get("decision", {})
        if isinstance(modifier_decision, dict) and modifier_decision.get("summary"):
            lines.append(f"  - Modification: {modifier_decision['summary']}")
        changed_files = modifier.get("changed_files", [])
        if isinstance(changed_files, list) and changed_files:
            lines.append(f"  - Changed files: {', '.join(str(item) for item in changed_files)}")
        verification = verifier.get("verification")
        if isinstance(verification, dict):
            lines.append(
                "  - Verification decision: "
                f"status={verification.get('status')}, approved={verification.get('approved')}, "
                f"summary={verification.get('message', '')}"
            )
        if feedback:
            verification_issues = verification.get("issues", []) if isinstance(verification, dict) else []
            verification_suggestions = (
                verification.get("suggestions", []) if isinstance(verification, dict) else []
            )
            lines.append("  - Verifier feedback returned to modifier:")
            lines.extend(f"    - Issue: {item}" for item in verification_issues)
            lines.extend(f"    - Suggestion: {item}" for item in verification_suggestions)
    return lines or ["- No modifier/verifier attempts recorded"]


def _format_pre_modification(
    pre_modification: dict[str, Any],
    test_generator: dict[str, Any],
) -> list[str]:
    if not pre_modification:
        return ["- Not run"]
    coverage = pre_modification.get("coverage", {})
    lines = [
        f"- Status: {pre_modification.get('status', 'unknown')}",
        f"- Message: {pre_modification.get('message', '')}",
        f"- Required generated tests: {pre_modification.get('requires_test_generation', False)}",
        f"- Target file covered lines: "
        f"{coverage.get('target_file_lines_covered', 0)}/{coverage.get('target_file_lines_total', 0)}",
    ]
    commands = pre_modification.get("commands", [])
    if isinstance(commands, list) and commands:
        lines.append("- Baseline commands:")
        lines.extend(
            f"  - `{command.get('command', '')}` => {command.get('exit_code', '')}"
            for command in commands
            if isinstance(command, dict)
        )
    generated_tests = pre_modification.get("generated_tests", [])
    if isinstance(generated_tests, list) and generated_tests:
        lines.append(f"- Generated behavior-locking tests: {', '.join(str(item) for item in generated_tests)}")
    if test_generator:
        decision = test_generator.get("decision", {})
        summary = decision.get("summary", "") if isinstance(decision, dict) else ""
        lines.append(f"- Test generator decision: {summary or 'recorded'}")
    return lines
