"""Command handlers for the refactor-agent CLI."""

from __future__ import annotations

import json
import sys

from suncli_py.refactor_agent.models import ProjectProfile, RefactorIssue, ScanResult
from suncli_py.refactor_agent.project_detector import ProjectDetector
from suncli_py.refactor_agent.scanner import JavaSmellScanner
from suncli_py.refactor_agent.storage import RefactorAgentStorage


class RefactorAgentError(Exception):
    """User-facing refactor-agent command error."""


def run_scan(*, output_format: str = "text") -> int:
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
    result = ScanResult(profile=profile, issues=issues, warnings=scanner.warnings)
    saved_path = RefactorAgentStorage(profile.root).save_scan_result(result)

    if output_format == "json":
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_project_profile(profile))
        print()
        print(format_scan_issues(issues, scanner.warnings, str(saved_path)))
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
