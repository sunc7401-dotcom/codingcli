"""Command handlers for the refactor-agent CLI."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

from suncli_py.refactor_agent.llm_assistant import RefactorLlmAssistant
from suncli_py.refactor_agent.models import (
    CharacterizationTestPlan,
    CommandResult,
    ProjectProfile,
    RefactorIssue,
    RefactorPlan,
    RiskLevel,
    ScanResult,
)
from suncli_py.refactor_agent.patcher import PatchError, RefactorPatcher
from suncli_py.refactor_agent.planner import RefactorPlanner
from suncli_py.refactor_agent.project_detector import ProjectDetector
from suncli_py.refactor_agent.report import ReportGenerator
from suncli_py.refactor_agent.rollback import RollbackError, TaskRollbacker
from suncli_py.refactor_agent.scanner import JavaSmellScanner
from suncli_py.refactor_agent.storage import RefactorAgentStorage
from suncli_py.refactor_agent.test_generator import CharacterizationTestGenerator
from suncli_py.refactor_agent.verifier import CommandRunner, VerificationPipeline, default_command_runner


class RefactorAgentError(Exception):
    """User-facing refactor-agent command error."""


def run_scan(*, output_format: str = "text", llm_assistant: RefactorLlmAssistant | None = None) -> int:
    profile = ProjectDetector(".").detect()

    if not profile.is_git_repo:
        raise RefactorAgentError("当前目录不是 Git 仓库：未发现 .git，且 git rev-parse 检测失败。")
    if not profile.is_maven_project:
        raise RefactorAgentError("当前目录不是 Maven 项目：未发现 pom.xml。")

    if not profile.is_git_clean and output_format == "text" and sys.stdin.isatty():
        answer = input("Git 工作区不干净，scan 不会写文件。是否继续？[y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("已取消 scan。")
            return 1

    scanner = JavaSmellScanner(profile.root)
    issues = scanner.scan()
    assistant = llm_assistant or RefactorLlmAssistant.from_config()
    if assistant is not None:
        issues = assistant.explain_issues(profile.root, issues)
    result = ScanResult(profile=profile, issues=issues, warnings=scanner.warnings)
    saved_path = RefactorAgentStorage(profile.root).save_scan_result(result)

    if output_format == "json":
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_project_profile(profile))
        print()
        print(format_scan_issues(issues, scanner.warnings, str(saved_path)))
    return 0


def run_plan(*, issue_id: str, llm_assistant: RefactorLlmAssistant | None = None) -> int:
    root = Path(".").resolve()
    storage = RefactorAgentStorage(root)
    try:
        issue = storage.find_issue(issue_id)
    except FileNotFoundError as err:
        raise RefactorAgentError("未找到扫描结果，请先运行 refactor-agent scan。") from err

    if issue is None:
        raise RefactorAgentError(f"未找到 issue: {issue_id}")

    plan = RefactorPlanner(root).create_plan(issue)
    assistant = llm_assistant or RefactorLlmAssistant.from_config()
    if assistant is not None:
        plan = assistant.enhance_plan(plan, issue)
    plan_json_path, plan_md_path = storage.save_plan(plan, issue)

    print(format_refactor_plan(plan, str(plan_json_path), str(plan_md_path)))
    return 0


def run_apply(
    *,
    issue_id: str,
    assume_yes: bool = False,
    llm_assistant: RefactorLlmAssistant | None = None,
) -> int:
    root = Path(".").resolve()
    storage = RefactorAgentStorage(root)
    loaded = storage.load_latest_plan_for_issue(issue_id)
    if loaded is None:
        raise RefactorAgentError(
            f"未找到 issue {issue_id} 的重构计划，请先运行 refactor-agent plan --issue {issue_id}。"
        )

    plan, issue, task_dir = loaded
    print(format_apply_confirmation(plan, issue))
    if not _confirm_apply(plan, assume_yes=assume_yes):
        print("已取消 apply，未写入任何文件。")
        return 1

    patcher = RefactorPatcher(root)
    try:
        assistant = llm_assistant or RefactorLlmAssistant.from_config()
        llm_edit_plan = assistant.generate_edit_plan(plan, issue) if assistant else None
        changes = patcher.generate_changes(plan, issue, llm_edit_plan=llm_edit_plan)
        result = patcher.apply_changes(plan, changes, task_dir)
    except PatchError as err:
        raise RefactorAgentError(str(err)) from err

    print(
        format_apply_result(
            result.changed_files,
            str(result.snapshot_path),
            str(result.patch_path),
            result.diff_text,
        )
    )
    return 0


def run_verify(*, issue_id: str | None = None, command_runner: CommandRunner | None = None) -> int:
    root = Path(".").resolve()
    storage = RefactorAgentStorage(root)
    loaded = _load_task(storage, issue_id=issue_id, task_id=None)
    plan, issue, task_dir = loaded
    result = VerificationPipeline(root, command_runner=command_runner).verify(plan, issue, task_dir)
    storage.save_verification(task_dir, result)
    _generate_report(root, storage, task_dir, plan, issue)
    print(format_verification_result(result))
    return 0 if result.status in {"passed", "warning"} else 1


def run_characterize(
    *,
    issue_id: str,
    assume_yes: bool = False,
    command_runner: CommandRunner | None = None,
) -> int:
    root = Path(".").resolve()
    storage = RefactorAgentStorage(root)
    plan, issue, task_dir = _load_task(storage, issue_id=issue_id, task_id=None)
    candidate = CharacterizationTestGenerator(root).create_plan(plan, issue)
    print(format_characterization_plan(candidate))
    if not _confirm_action("是否写入候选行为锁定测试？[y/N] ", assume_yes=assume_yes):
        storage.save_characterization_plan(task_dir, candidate)
        print("已取消 characterize，未写入测试文件。")
        return 1

    destination = _resolve_repo_file(root, candidate.destination_file)
    if destination.exists():
        raise RefactorAgentError(f"候选测试文件已存在，拒绝覆盖: {candidate.destination_file}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(candidate.content, encoding="utf-8")
    precheck = _run_precheck(command_runner or default_command_runner, root)
    confirmed = CharacterizationTestPlan(
        issue_id=candidate.issue_id,
        target_class=candidate.target_class,
        target_methods=candidate.target_methods,
        test_framework=candidate.test_framework,
        destination_file=candidate.destination_file,
        assertion_intent=candidate.assertion_intent,
        content=candidate.content,
        user_confirmed=True,
        pre_refactor_test_result=precheck,
        usable_as_refactor_guard=precheck.exit_code == 0,
    )
    storage.save_characterization_plan(task_dir, confirmed)
    _generate_report(root, storage, task_dir, plan, issue)
    print(format_characterization_result(confirmed))
    return 0 if confirmed.usable_as_refactor_guard else 1


def run_rollback(*, task_id: str | None = None, assume_yes: bool = False) -> int:
    root = Path(".").resolve()
    storage = RefactorAgentStorage(root)
    plan, issue, task_dir = _load_task(storage, issue_id=None, task_id=task_id)
    rollbacker = TaskRollbacker(root)
    try:
        result = rollbacker.rollback(task_dir, force=False)
        if result.status == "conflict":
            print(format_rollback_result(result))
            if not _confirm_action("检测到冲突，是否仍然恢复任务前文件？[y/N] ", assume_yes=assume_yes):
                storage.save_rollback(task_dir, result)
                _generate_report(root, storage, task_dir, plan, issue)
                return 1
            result = rollbacker.rollback(task_dir, force=True)
    except RollbackError as err:
        raise RefactorAgentError(str(err)) from err
    storage.save_rollback(task_dir, result)
    _generate_report(root, storage, task_dir, plan, issue)
    print(format_rollback_result(result))
    return 0 if result.status == "rolled_back" else 1


def run_report(*, task_id: str | None = None, latest: bool = False) -> int:
    root = Path(".").resolve()
    storage = RefactorAgentStorage(root)
    if latest and task_id is None:
        latest_path = storage.base_dir / "reports" / "latest.md"
        if not latest_path.is_file():
            raise RefactorAgentError("未找到 latest 报告。")
        print(latest_path.read_text(encoding="utf-8"))
        return 0

    plan, issue, task_dir = _load_task(storage, issue_id=None, task_id=task_id)
    report_path = _generate_report(root, storage, task_dir, plan, issue)
    print(report_path.read_text(encoding="utf-8"))
    return 0


def format_project_profile(profile: ProjectProfile) -> str:
    lines = [
        "项目 Profile",
        f"- 根目录: {profile.root}",
        f"- Git 仓库: {_yes_no(profile.is_git_repo)}",
        f"- Maven 项目: {_yes_no(profile.is_maven_project)}",
        f"- Java 源码目录: {_yes_no(profile.has_main_java)}",
        f"- Java 测试目录: {_yes_no(profile.has_test_java)}",
        f"- Git 工作区干净: {_yes_no(profile.is_git_clean)}",
        f"- Maven: {profile.maven_version or '未检测到'}",
        f"- Java: {profile.java_version or '未检测到'}",
    ]

    if profile.modules:
        lines.append("- Maven 模块:")
        for module in profile.modules:
            lines.append(
                f"  - {module.name}: main={_yes_no(module.has_main_java)}, test={_yes_no(module.has_test_java)}"
            )
    else:
        lines.append("- Maven 模块: 未检测到多模块结构")

    if profile.warnings:
        lines.append("警告:")
        for warning in profile.warnings:
            lines.append(f"- {warning}")

    return "\n".join(lines)


def _yes_no(value: bool) -> str:
    return "是" if value else "否"


def format_scan_issues(issues: list[RefactorIssue], warnings: list[str], saved_path: str) -> str:
    lines = [f"坏味道扫描结果: 发现 {len(issues)} 个 issue"]
    if issues:
        for issue in issues:
            lines.append(
                f"- [{issue.severity.upper()}] {issue.id} {issue.type}: "
                f"{issue.file_path}:{issue.start_line} {issue.symbol or ''}".rstrip()
            )
            lines.append(f"  建议: {issue.suggested_refactoring}")
            lines.append(f"  自动化适用: {_yes_no(issue.auto_applicable)} | 风险: {issue.risk_level}")
    else:
        lines.append("- 未发现阶段二规则覆盖的坏味道。")

    if warnings:
        lines.append("扫描警告:")
        for warning in warnings:
            lines.append(f"- {warning}")

    lines.append(f"结构化结果已保存: {saved_path}")
    return "\n".join(lines)


def format_refactor_plan(plan: RefactorPlan, plan_json_path: str, plan_md_path: str) -> str:
    lines = [
        "重构计划",
        f"- Task: {plan.task_id}",
        f"- Issue: {plan.issue_id}",
        f"- 目标: {plan.goal}",
        f"- 方式: {plan.refactoring_type}",
        f"- 风险: {plan.risk_level}",
        f"- 修改文件: {', '.join(plan.files_to_modify)}",
        f"- 覆盖评估: {plan.coverage_assessment.confidence}",
        f"- 需要行为锁定测试: {_yes_no(plan.coverage_assessment.needs_characterization_test)}",
        "- 验证命令:",
        *[f"  - {command}" for command in plan.verification_commands],
        "- 预期修改:",
        *[f"  - {change}" for change in plan.expected_changes],
        "- 风险原因:",
        *[f"  - {reason}" for reason in plan.risk_reasons],
        f"- 计划 JSON: {plan_json_path}",
        f"- 计划 Markdown: {plan_md_path}",
    ]
    return "\n".join(lines)


def format_apply_confirmation(plan: RefactorPlan, issue: RefactorIssue) -> str:
    lines = [
        "即将应用重构",
        f"- Task: {plan.task_id}",
        f"- Issue: {issue.id}",
        f"- 目标: {plan.goal}",
        f"- 位置: {issue.file_path}:{issue.start_line}-{issue.end_line}",
        f"- 方式: {plan.refactoring_type}",
        f"- 风险: {plan.risk_level}",
        f"- 修改文件: {', '.join(plan.files_to_modify)}",
        "- 验证命令:",
        *[f"  - {command}" for command in plan.verification_commands],
        f"- 回滚方式: {plan.rollback_strategy}",
    ]
    if plan.risk_reasons:
        lines.append("- 风险原因:")
        lines.extend(f"  - {reason}" for reason in plan.risk_reasons)
    return "\n".join(lines)


def format_apply_result(changed_files: list[str], snapshot_path: str, patch_path: str, diff_text: str) -> str:
    lines = [
        "apply 完成",
        f"- 快照: {snapshot_path}",
        f"- Patch: {patch_path}",
        f"- 修改文件: {', '.join(changed_files)}",
        "",
        "Diff:",
        diff_text.rstrip(),
    ]
    return "\n".join(lines)


def format_verification_result(result) -> str:
    lines = [
        f"verify {result.status}",
        f"- 结论: {result.message}",
        "- 命令:",
        *[f"  - {command.command}: exit {command.exit_code}" for command in result.commands],
        "- 覆盖感知:",
        f"  - JaCoCo: {_yes_no(result.coverage.jacoco_report_found)}",
        f"  - changed lines: {result.coverage.changed_lines_covered}/{result.coverage.changed_lines_total}",
        f"  - confidence: {result.coverage.confidence}",
        f"  - recommendation: {result.coverage.recommendation}",
    ]
    if result.static_findings:
        lines.append("- 静态检查提示:")
        lines.extend(f"  - {finding}" for finding in result.static_findings)
    return "\n".join(lines)


def format_characterization_plan(plan: CharacterizationTestPlan) -> str:
    lines = [
        "候选行为锁定测试",
        f"- Issue: {plan.issue_id}",
        f"- Target: {plan.target_class}",
        f"- Destination: {plan.destination_file}",
        f"- Framework: {plan.test_framework}",
        "- 断言意图:",
        *[f"  - {item}" for item in plan.assertion_intent],
        "",
        "Preview:",
        plan.content.rstrip(),
    ]
    return "\n".join(lines)


def format_characterization_result(plan: CharacterizationTestPlan) -> str:
    precheck = plan.pre_refactor_test_result
    exit_code = precheck.exit_code if precheck else "not-run"
    return "\n".join(
        [
            "characterize 完成",
            f"- 文件: {plan.destination_file}",
            f"- 预验证 exit: {exit_code}",
            f"- 可作为重构 guard: {_yes_no(plan.usable_as_refactor_guard)}",
        ]
    )


def format_rollback_result(result) -> str:
    lines = [
        f"rollback {result.status}",
        f"- Task: {result.task_id}",
        f"- 恢复文件: {', '.join(result.restored_files) or 'none'}",
        f"- 冲突: {', '.join(result.conflicts) or 'none'}",
        f"- 说明: {result.message}",
    ]
    return "\n".join(lines)


def _confirm_apply(plan: RefactorPlan, *, assume_yes: bool) -> bool:
    if assume_yes and plan.risk_level == RiskLevel.LOW:
        return True
    try:
        answer = input("是否应用该重构？[y/N] ").strip().lower()
    except (EOFError, OSError):
        return False
    return answer in {"y", "yes"}


def _confirm_action(prompt: str, *, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    try:
        answer = input(prompt).strip().lower()
    except (EOFError, OSError):
        return False
    return answer in {"y", "yes"}


def _load_task(
    storage: RefactorAgentStorage,
    *,
    issue_id: str | None,
    task_id: str | None,
) -> tuple[RefactorPlan, RefactorIssue, Path]:
    if issue_id:
        loaded = storage.load_latest_plan_for_issue(issue_id)
        if loaded is None:
            raise RefactorAgentError(f"未找到 issue {issue_id} 的任务计划。")
        return loaded

    task_dir = storage.task_dir(task_id) if task_id else storage.latest_task_dir()
    if task_dir is None or not task_dir.is_dir():
        raise RefactorAgentError("未找到可用任务。")
    plan, issue = storage.load_task_plan(task_dir)
    return plan, issue, task_dir


def _generate_report(
    root: Path,
    storage: RefactorAgentStorage,
    task_dir: Path,
    plan: RefactorPlan,
    issue: RefactorIssue,
) -> Path:
    return ReportGenerator(root).generate(
        task_dir,
        plan,
        issue,
        storage.load_verification(task_dir),
        storage.load_rollback(task_dir),
        storage.load_characterization_plan(task_dir),
    )


def _resolve_repo_file(root: Path, file_path: str) -> Path:
    relative = Path(file_path.replace("\\", "/").lstrip("/"))
    if relative.is_absolute():
        raise RefactorAgentError(f"路径必须位于仓库内: {file_path}")
    destination = (root / relative).resolve()
    try:
        destination.relative_to(root)
    except ValueError as err:
        raise RefactorAgentError(f"路径越界: {file_path}") from err
    return destination


def _run_precheck(command_runner: CommandRunner, root: Path) -> CommandResult:
    command: Sequence[str] = ("mvn", "test")
    try:
        result = command_runner(command, root)
    except (FileNotFoundError, OSError) as err:
        return CommandResult(command="mvn test", exit_code=127, stderr=str(err))
    return CommandResult(
        command="mvn test",
        exit_code=result.returncode,
        stdout=(result.stdout or "")[-4000:],
        stderr=(result.stderr or "")[-4000:],
    )
