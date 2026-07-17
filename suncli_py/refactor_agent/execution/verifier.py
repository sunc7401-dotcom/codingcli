"""Verification pipeline for refactor-agent tasks."""

from __future__ import annotations

import difflib
import json
import shlex
import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from suncli_py.refactor_agent.analysis.coverage import CoverageAnalyzer
from suncli_py.refactor_agent.core.models import (
    CommandResult,
    CoverageAssessment,
    PreModificationResult,
    RefactorIssue,
    RefactorPlan,
    VerificationResult,
)
from suncli_py.refactor_agent.execution.workspace import capture_workspace_manifest

CommandRunner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]

COMPILE_COMMAND = "mvn -q -DskipTests compile"
TEST_COMPILE_COMMAND = "mvn -q -DskipTests test-compile"
TEST_COMMAND = "mvn test"
JACOCO_TEST_COMMAND = "mvn org.jacoco:jacoco-maven-plugin:prepare-agent test"
JACOCO_REPORT_COMMAND = "mvn org.jacoco:jacoco-maven-plugin:report"
# Backward-compatible name for callers that only need the report phase.
COVERAGE_COMMAND = JACOCO_REPORT_COMMAND
DEFAULT_VERIFICATION_COMMANDS = (COMPILE_COMMAND, JACOCO_TEST_COMMAND, JACOCO_REPORT_COMMAND)


def default_command_runner(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    executable = shutil.which(command[0]) or command[0]
    return subprocess.run(
        [executable, *command[1:]],
        cwd=str(cwd),
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        text=True,
        timeout=180,
    )


class VerificationPipeline:
    def __init__(self, root: str | Path, command_runner: CommandRunner | None = None) -> None:
        self.root = Path(root).resolve()
        self._run = command_runner or default_command_runner

    def verify(self, plan: RefactorPlan, issue: RefactorIssue, task_dir: Path) -> VerificationResult:
        commands = [
            self.run_command(COMPILE_COMMAND),
            self.run_command(JACOCO_TEST_COMMAND),
        ]
        coverage_report_command = self.run_command(JACOCO_REPORT_COMMAND)
        commands.append(coverage_report_command)

        coverage = self.coverage_assessment(plan, issue)
        diff_summary, diff_findings = self.inspect_diff(plan, task_dir)
        static_findings = [*diff_findings, *self.inspect_workspace(plan, task_dir)]

        failed = [result for result in commands[:2] if result.exit_code != 0]
        if failed:
            return VerificationResult(
                status="failed",
                commands=commands,
                coverage=coverage,
                static_findings=static_findings,
                diff_summary=diff_summary,
                message=_failure_message(failed[0]),
            )

        if static_findings:
            return VerificationResult(
                status="failed",
                commands=commands,
                coverage=coverage,
                static_findings=static_findings,
                diff_summary=diff_summary,
                message="工作区完整性检查失败: " + "; ".join(static_findings),
            )

        if coverage_report_command.exit_code != 0 or coverage.needs_characterization_test:
            message = coverage.recommendation
            if coverage_report_command.exit_code != 0:
                message = "JaCoCo 覆盖命令执行失败，已降级为覆盖不足警告。"
            return VerificationResult(
                status="warning",
                commands=commands,
                coverage=coverage,
                static_findings=static_findings,
                diff_summary=diff_summary,
                message=message,
            )

        return VerificationResult(
            status="passed",
            commands=commands,
            coverage=coverage,
            static_findings=static_findings,
            diff_summary=diff_summary,
            message="编译、测试与覆盖感知通过。",
        )

    def run_command(self, command: str) -> CommandResult:
        try:
            result = self._run(shlex.split(command), self.root)
        except (FileNotFoundError, OSError, subprocess.SubprocessError) as err:
            return CommandResult(command=command, exit_code=127, stderr=str(err))
        return CommandResult(
            command=command,
            exit_code=result.returncode,
            stdout=(result.stdout or "")[-4000:],
            stderr=(result.stderr or "")[-4000:],
        )

    def coverage_assessment(self, plan: RefactorPlan, issue: RefactorIssue) -> CoverageAssessment:
        return CoverageAnalyzer(self.root).assess(plan, issue)

    def inspect_diff(self, plan: RefactorPlan, task_dir: Path) -> tuple[str, list[str]]:
        return _actual_workspace_diff(self.root, plan, task_dir)

    def inspect_workspace(self, plan: RefactorPlan, task_dir: Path) -> list[str]:
        return _workspace_findings(self.root, plan, task_dir)


class PreModificationVerifier:
    """Establish a clean, covered baseline before any production edit is allowed."""

    def __init__(self, root: str | Path, command_runner: CommandRunner | None = None) -> None:
        self.pipeline = VerificationPipeline(root, command_runner=command_runner)

    def verify(self, plan: RefactorPlan, issue: RefactorIssue) -> PreModificationResult:
        commands = [
            self.pipeline.run_command(COMPILE_COMMAND),
            self.pipeline.run_command(JACOCO_TEST_COMMAND),
            self.pipeline.run_command(JACOCO_REPORT_COMMAND),
        ]
        infrastructure = next((result for result in commands if result.exit_code == 127), None)
        if infrastructure is not None:
            message = (
                f"修改前验证基础设施不可用: {infrastructure.command}: "
                f"{infrastructure.stderr or infrastructure.stdout}"
            )
            return PreModificationResult(
                status="infrastructure_error",
                commands=commands,
                coverage=plan.coverage_assessment,
                requires_test_generation=False,
                message=message,
                infrastructure_error=message,
            )

        failed_baseline = next((result for result in commands[:2] if result.exit_code != 0), None)
        if failed_baseline is not None:
            return PreModificationResult(
                status="baseline_failed",
                commands=commands,
                coverage=plan.coverage_assessment,
                requires_test_generation=False,
                message="原始代码的编译或测试未通过，禁止开始自动修改。\n" + _failure_message(failed_baseline),
            )

        coverage = self.pipeline.coverage_assessment(plan, issue)
        if commands[2].exit_code != 0:
            return PreModificationResult(
                status="coverage_unavailable",
                commands=commands,
                coverage=coverage,
                requires_test_generation=False,
                message="修改前 JaCoCo 命令失败，禁止开始自动修改。\n" + _failure_message(commands[2]),
            )

        if not coverage.jacoco_report_found:
            return PreModificationResult(
                status="coverage_gap",
                commands=commands,
                coverage=coverage,
                requires_test_generation=True,
                message="JaCoCo 命令成功但没有生成报告，按无可用测试覆盖处理并先生成行为锁定测试。",
            )

        requires_generation = bool(
            coverage.needs_characterization_test or coverage.target_file_lines_covered == 0
        )
        return PreModificationResult(
            status="coverage_gap" if requires_generation else "ready",
            commands=commands,
            coverage=coverage,
            requires_test_generation=requires_generation,
            message=(
                "目标代码缺少充分覆盖，将先由测试生成 Agent 在原始代码上补充并验证测试。"
                if requires_generation
                else "原始代码编译、测试与目标覆盖基线均已通过。"
            ),
        )


def _actual_workspace_diff(root: Path, plan: RefactorPlan, task_dir: Path) -> tuple[str, list[str]]:
    findings: list[str] = []
    planned_files = {_normalize_diff_path(file_path) for file_path in plan.files_to_modify}
    generated_tests = {
        _normalize_diff_path(file_path) for file_path in plan.coverage_assessment.generated_tests
    }
    snapshot = _read_snapshot(task_dir, findings)
    if snapshot is None:
        return "", findings
    before_entries = {
        _normalize_diff_path(str(entry.get("path") or "")): entry
        for entry in snapshot.get("files", [])
        if isinstance(entry, dict) and entry.get("path")
    }
    diff_parts: list[str] = []
    for file_path in sorted(planned_files | generated_tests):
        current_path = _safe_workspace_path(root, file_path, findings)
        if current_path is None or not current_path.is_file():
            findings.append(f"验证时文件不存在: {file_path}")
            continue
        if file_path in planned_files:
            entry = before_entries.get(file_path)
            before_copy = task_dir / str(entry.get("before_copy") or "") if entry else None
            if before_copy is None or not before_copy.is_file():
                findings.append(f"初始快照缺少计划文件: {file_path}")
                continue
            before_text = before_copy.read_text(encoding="utf-8")
            from_file = f"a/{file_path}"
        else:
            before_text = ""
            from_file = "/dev/null"
        after_text = current_path.read_text(encoding="utf-8")
        diff_parts.extend(
            difflib.unified_diff(
                before_text.splitlines(keepends=True),
                after_text.splitlines(keepends=True),
                fromfile=from_file,
                tofile=f"b/{file_path}",
                lineterm="\n",
            )
        )
    diff_text = "".join(diff_parts)
    if not diff_text:
        findings.append("实际工作区未发现计划内代码变化。")
    return diff_text, findings


def _workspace_findings(root: Path, plan: RefactorPlan, task_dir: Path) -> list[str]:
    findings: list[str] = []
    snapshot = _read_snapshot(task_dir, findings)
    if snapshot is None:
        return findings
    raw_manifest = snapshot.get("workspace_manifest")
    if not isinstance(raw_manifest, dict):
        return ["snapshot.json 缺少 workspace_manifest，无法独立验证工作区范围。"]
    before_manifest = {
        _normalize_diff_path(str(path)): str(digest)
        for path, digest in raw_manifest.items()
        if str(path) and str(digest)
    }
    current_manifest = capture_workspace_manifest(root)
    changed_files = {
        path
        for path in before_manifest.keys() | current_manifest.keys()
        if before_manifest.get(path) != current_manifest.get(path)
    }
    allowed_files = {
        *(_normalize_diff_path(path) for path in plan.files_to_modify),
        *(_normalize_diff_path(path) for path in plan.coverage_assessment.generated_tests),
    }
    for file_path in sorted(changed_files - allowed_files):
        findings.append(f"任务开始后出现计划外工作区变化: {file_path}")
    return findings


def _read_snapshot(task_dir: Path, findings: list[str]) -> dict[str, Any] | None:
    snapshot_path = task_dir / "snapshot.json"
    if not snapshot_path.is_file():
        findings.append("未找到 snapshot.json，无法核对真实工作区。")
        return None
    try:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as err:
        findings.append(f"无法读取 snapshot.json: {err}")
        return None
    if not isinstance(snapshot, dict):
        findings.append("snapshot.json 格式错误。")
        return None
    return snapshot


def _safe_workspace_path(root: Path, file_path: str, findings: list[str]) -> Path | None:
    path = (root / file_path).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        findings.append(f"验证路径越出项目根目录: {file_path}")
        return None
    return path


def _normalize_diff_path(file_path: str) -> str:
    return file_path.replace("\\", "/").lstrip("/")


def _failure_message(result: CommandResult) -> str:
    output = (result.stderr or result.stdout).strip()
    if not output:
        output = "命令无输出。"
    return f"验证命令失败: {result.command}\n{output[-1000:]}"
