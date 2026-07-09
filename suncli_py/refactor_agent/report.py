"""Refactor-agent evidence chain report generation."""

from __future__ import annotations

import json
from pathlib import Path

from suncli_py.refactor_agent.models import (
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
            "## Verification",
        ]
        if verification:
            lines.extend(
                [
                    f"- Status: {verification.status}",
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


def _load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
