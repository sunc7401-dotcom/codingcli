"""Verification pipeline for refactor-agent tasks."""

from __future__ import annotations

import shlex
import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from suncli_py.refactor_agent.coverage import CoverageAnalyzer
from suncli_py.refactor_agent.models import CommandResult, RefactorIssue, RefactorPlan, VerificationResult

CommandRunner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]


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
            self._run_command("mvn -q -DskipTests compile"),
            self._run_command("mvn test"),
        ]
        coverage_command = self._run_command(
            "mvn org.jacoco:jacoco-maven-plugin:prepare-agent test org.jacoco:jacoco-maven-plugin:report"
        )
        commands.append(coverage_command)

        coverage = CoverageAnalyzer(self.root).assess(plan, issue)
        diff_summary = _read_text_if_exists(task_dir / "diff_summary.txt")
        static_findings = _static_findings(plan, task_dir)

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

    def _run_command(self, command: str) -> CommandResult:
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
