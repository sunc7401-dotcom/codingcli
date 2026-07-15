"""Verification pipeline for refactor-agent tasks."""

from __future__ import annotations

import shlex
import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from suncli_py.refactor_agent.analysis.coverage import CoverageAnalyzer
from suncli_py.refactor_agent.core.models import (
    CommandResult,
    CoverageAssessment,
    PreModificationResult,
    RefactorIssue,
    RefactorPlan,
    VerificationResult,
)

CommandRunner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]

COMPILE_COMMAND = "mvn -q -DskipTests compile"
TEST_COMPILE_COMMAND = "mvn -q -DskipTests test-compile"
TEST_COMMAND = "mvn test"
COVERAGE_COMMAND = "mvn org.jacoco:jacoco-maven-plugin:prepare-agent test org.jacoco:jacoco-maven-plugin:report"
DEFAULT_VERIFICATION_COMMANDS = (COMPILE_COMMAND, TEST_COMMAND, COVERAGE_COMMAND)


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
            self.run_command(TEST_COMMAND),
        ]
        coverage_command = self.run_command(COVERAGE_COMMAND)
        commands.append(coverage_command)

        coverage = self.coverage_assessment(plan, issue)
        diff_summary, static_findings = self.inspect_diff(plan, task_dir)

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

        if coverage_command.exit_code != 0 or coverage.needs_characterization_test or static_findings:
            message = coverage.recommendation
            if coverage_command.exit_code != 0:
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
        return _read_text_if_exists(task_dir / "diff_summary.txt"), _static_findings(plan, task_dir)


class PreModificationVerifier:
    """Establish a clean, covered baseline before any production edit is allowed."""

    def __init__(self, root: str | Path, command_runner: CommandRunner | None = None) -> None:
        self.pipeline = VerificationPipeline(root, command_runner=command_runner)

    def verify(self, plan: RefactorPlan, issue: RefactorIssue) -> PreModificationResult:
        commands = [
            self.pipeline.run_command(COMPILE_COMMAND),
            self.pipeline.run_command(TEST_COMMAND),
            self.pipeline.run_command(COVERAGE_COMMAND),
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


def _read_text_if_exists(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _static_findings(plan: RefactorPlan, task_dir: Path) -> list[str]:
    diff_text = _read_text_if_exists(task_dir / "patch.diff")
    if not diff_text:
        return ["未找到 patch.diff，无法核对 diff 证据。"]
    findings: list[str] = []
    for file_path in plan.files_to_modify:
        marker = f"b/{file_path}"
        if marker not in diff_text:
            findings.append(f"计划文件未出现在 diff 中: {file_path}")
    return findings


def _failure_message(result: CommandResult) -> str:
    output = (result.stderr or result.stdout).strip()
    if not output:
        output = "命令无输出。"
    return f"验证命令失败: {result.command}\n{output[-1000:]}"
