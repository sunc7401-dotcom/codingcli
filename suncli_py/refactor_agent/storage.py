"""Repository-local storage for refactor-agent scan state."""

from __future__ import annotations

import json
from pathlib import Path

from suncli_py.refactor_agent.models import (
    CharacterizationTestPlan,
    RefactorIssue,
    RefactorPlan,
    RollbackResult,
    ScanResult,
    VerificationResult,
)


class RefactorAgentStorage:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.base_dir = self.root / ".paicli" / "refactor-agent"

    def save_scan_result(self, result: ScanResult) -> Path:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.base_dir / "issues.json"
        output_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return output_path

    def load_scan_result(self) -> ScanResult:
        input_path = self.base_dir / "issues.json"
        data = json.loads(input_path.read_text(encoding="utf-8"))
        return ScanResult.from_dict(data)

    def find_issue(self, issue_id: str) -> RefactorIssue | None:
        normalized = issue_id.strip().upper()
        for issue in self.load_scan_result().issues:
            if issue.id.upper() == normalized:
                return issue
        return None

    def save_plan(self, plan: RefactorPlan, issue: RefactorIssue) -> tuple[Path, Path]:
        task_dir = self.base_dir / "tasks" / plan.task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        issue_path = task_dir / "issue.json"
        plan_json_path = task_dir / "plan.json"
        plan_md_path = task_dir / "plan.md"
        issue_path.write_text(json.dumps(issue.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        plan_json_path.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        plan_md_path.write_text(_format_plan_markdown(plan), encoding="utf-8")
        return plan_json_path, plan_md_path

    def task_dir(self, task_id: str) -> Path:
        return self.base_dir / "tasks" / task_id

    def latest_task_dir(self) -> Path | None:
        tasks_dir = self.base_dir / "tasks"
        if not tasks_dir.is_dir():
            return None
        candidates = [path for path in tasks_dir.iterdir() if path.is_dir()]
        if not candidates:
            return None
        return max(candidates, key=lambda path: path.stat().st_mtime)

    def load_latest_plan_for_issue(self, issue_id: str) -> tuple[RefactorPlan, RefactorIssue, Path] | None:
        normalized = issue_id.strip().upper()
        tasks_dir = self.base_dir / "tasks"
        if not tasks_dir.is_dir():
            return None

        matches: list[tuple[float, RefactorPlan, RefactorIssue, Path]] = []
        for task_dir in tasks_dir.iterdir():
            plan_path = task_dir / "plan.json"
            issue_path = task_dir / "issue.json"
            if not plan_path.is_file() or not issue_path.is_file():
                continue
            plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
            if str(plan_data.get("issue_id", "")).upper() != normalized:
                continue
            issue_data = json.loads(issue_path.read_text(encoding="utf-8"))
            matches.append(
                (
                    plan_path.stat().st_mtime,
                    RefactorPlan.from_dict(plan_data),
                    RefactorIssue.from_dict(issue_data),
                    task_dir,
                )
            )

        if not matches:
            return None
        _, plan, issue, task_dir = max(matches, key=lambda item: item[0])
        return plan, issue, task_dir

    def load_task_plan(self, task_dir: Path) -> tuple[RefactorPlan, RefactorIssue]:
        plan_data = json.loads((task_dir / "plan.json").read_text(encoding="utf-8"))
        issue_data = json.loads((task_dir / "issue.json").read_text(encoding="utf-8"))
        return RefactorPlan.from_dict(plan_data), RefactorIssue.from_dict(issue_data)

    def save_verification(self, task_dir: Path, result: VerificationResult) -> Path:
        path = task_dir / "verification.json"
        path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load_verification(self, task_dir: Path) -> VerificationResult | None:
        path = task_dir / "verification.json"
        if not path.is_file():
            return None
        return VerificationResult.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save_characterization_plan(self, task_dir: Path, plan: CharacterizationTestPlan) -> Path:
        path = task_dir / "characterization_plan.json"
        path.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load_characterization_plan(self, task_dir: Path) -> CharacterizationTestPlan | None:
        path = task_dir / "characterization_plan.json"
        if not path.is_file():
            return None
        return CharacterizationTestPlan.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save_rollback(self, task_dir: Path, result: RollbackResult) -> Path:
        path = task_dir / "rollback.json"
        path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load_rollback(self, task_dir: Path) -> RollbackResult | None:
        path = task_dir / "rollback.json"
        if not path.is_file():
            return None
        return RollbackResult.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _format_plan_markdown(plan: RefactorPlan) -> str:
    lines = [
        f"# Refactor Plan {plan.task_id}",
        "",
        f"- Issue: {plan.issue_id}",
        f"- Goal: {plan.goal}",
        f"- Refactoring: {plan.refactoring_type}",
        f"- Risk: {plan.risk_level}",
        f"- Requires confirmation: {'yes' if plan.requires_user_confirmation else 'no'}",
        "",
        "## Files To Modify",
        *[f"- {file_path}" for file_path in plan.files_to_modify],
        "",
        "## Expected Changes",
        *[f"- {change}" for change in plan.expected_changes],
        "",
        "## Out Of Scope",
        *[f"- {item}" for item in plan.out_of_scope],
        "",
        "## Risk Reasons",
        *[f"- {reason}" for reason in plan.risk_reasons],
        "",
        "## Verification Commands",
        *[f"- `{command}`" for command in plan.verification_commands],
        "",
        "## Coverage Assessment",
        f"- Related tests: {', '.join(plan.coverage_assessment.related_tests) or 'none'}",
        f"- Confidence: {plan.coverage_assessment.confidence}",
        f"- Needs characterization test: {'yes' if plan.coverage_assessment.needs_characterization_test else 'no'}",
        f"- Recommendation: {plan.coverage_assessment.recommendation}",
        "",
        "## Rollback",
        plan.rollback_strategy,
    ]
    return "\n".join(lines) + "\n"
