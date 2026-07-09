"""Small-step refactor plan generation."""

from __future__ import annotations

import time
from pathlib import Path

from suncli_py.refactor_agent.java_context import JavaContextCollector
from suncli_py.refactor_agent.models import (
    CoverageAssessment,
    JavaContext,
    RefactoringType,
    RefactorIssue,
    RefactorPlan,
    RiskLevel,
    SmellType,
)
from suncli_py.refactor_agent.project_detector import ProjectDetector


class RefactorPlanner:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def create_plan(self, issue: RefactorIssue) -> RefactorPlan:
        profile = ProjectDetector(self.root).detect()
        context = JavaContextCollector(self.root).collect(issue)
        coverage = _assess_coverage(issue, context)

        return RefactorPlan(
            task_id=_task_id(issue.id),
            issue_id=issue.id,
            goal=_goal(issue),
            refactoring_type=issue.suggested_refactoring,
            files_to_modify=_files_to_modify(issue),
            expected_changes=_expected_changes(issue),
            out_of_scope=_out_of_scope(issue),
            risk_level=_effective_risk(issue.risk_level, coverage),
            risk_reasons=_risk_reasons(issue, coverage, profile.is_git_clean),
            verification_commands=["mvn -q -DskipTests compile", "mvn test"],
            rollback_strategy="应用阶段将创建任务级快照；回滚时只恢复本任务计划内文件，不使用 git reset --hard。",
            coverage_assessment=coverage,
            requires_user_confirmation=True,
            context=context,
            planning_source="rule-fallback",
        )


def _task_id(issue_id: str) -> str:
    return f"{issue_id.lower()}-{int(time.time())}"


def _goal(issue: RefactorIssue) -> str:
    target = issue.symbol or issue.file_path
    match issue.type:
        case SmellType.LONG_METHOD:
            return f"拆分长方法 {target}，降低方法规模和理解成本。"
        case SmellType.LARGE_CLASS:
            return f"为过大类 {target} 生成职责拆分计划。"
        case SmellType.COMPLEX_CONDITION:
            return f"简化 {target} 中的复杂条件表达式。"
        case SmellType.DUPLICATE_CODE:
            return "定位重复代码并规划共享逻辑提取。"
        case SmellType.DEAD_CODE:
            return f"移除未使用的 private 代码 {target}。"
        case SmellType.UNCLEAR_NAMING:
            return f"改善命名 {target}，让代码意图更清晰。"


def _files_to_modify(issue: RefactorIssue) -> list[str]:
    return [issue.file_path]


def _expected_changes(issue: RefactorIssue) -> list[str]:
    match issue.suggested_refactoring:
        case RefactoringType.EXTRACT_METHOD:
            return [
                "只在目标文件内提取一到两个小方法。",
                "保持原方法对外签名不变。",
                "避免混入格式化或无关重命名。",
            ]
        case RefactoringType.EXTRACT_CLASS:
            return [
                "阶段三只生成拆分类职责建议，不在 MVP 默认自动应用 Extract Class。",
                "后续 apply 阶段应要求强确认和测试覆盖检查。",
            ]
        case RefactoringType.INTRODUCE_EXPLAINING_VARIABLE:
            return [
                "为复杂布尔表达式引入解释性变量或小方法。",
                "保持条件判断语义不变。",
            ]
        case RefactoringType.REPLACE_DUPLICATE_LOGIC:
            return [
                "对重复片段提取共享方法或复用已有方法。",
                "一次只处理一个重复代码族。",
            ]
        case RefactoringType.REMOVE_DEAD_CODE:
            return [
                "删除确认未被引用的 private 方法或字段。",
                "不删除 public/protected API 或框架反射可能使用的成员。",
            ]
        case RefactoringType.RENAME:
            return [
                "仅重命名局部变量或低风险私有符号。",
                "不重命名 public API、序列化字段或框架绑定名称。",
            ]


def _out_of_scope(issue: RefactorIssue) -> list[str]:
    common = [
        "不格式化整个项目。",
        "不修改计划文件之外的文件。",
        "不改变外部可见行为。",
    ]
    if issue.risk_level == RiskLevel.HIGH:
        common.append("高风险重构在 MVP 中默认只输出计划，不自动应用。")
    return common


def _assess_coverage(issue: RefactorIssue, context: JavaContext) -> CoverageAssessment:
    has_tests = bool(context.related_tests)
    high_or_medium = issue.risk_level in {RiskLevel.HIGH, RiskLevel.MEDIUM}
    needs_characterization = not has_tests and high_or_medium
    confidence = "medium" if has_tests else "low"
    recommendation = (
        "已发现相关测试类；apply 阶段仍需运行 mvn test 并在覆盖感知阶段确认触达修改区域。"
        if has_tests
        else "未发现对应测试类；建议先生成 characterization test，再进入自动重构。"
    )
    return CoverageAssessment(
        has_related_test_class=has_tests,
        related_tests=context.related_tests,
        confidence=confidence,
        needs_characterization_test=needs_characterization,
        recommendation=recommendation,
    )


def _effective_risk(risk: RiskLevel, coverage: CoverageAssessment) -> RiskLevel:
    if coverage.needs_characterization_test and risk == RiskLevel.LOW:
        return RiskLevel.MEDIUM
    return risk


def _risk_reasons(issue: RefactorIssue, coverage: CoverageAssessment, is_git_clean: bool) -> list[str]:
    reasons = [
        f"扫描阶段风险等级为 {issue.risk_level}。",
        *[evidence.message for evidence in issue.evidence],
    ]
    if not coverage.has_related_test_class:
        reasons.append("未发现相关测试类，mvn test 通过也不一定覆盖本次修改。")
    if not is_git_clean:
        reasons.append("Git 工作区不干净，apply 前必须再次确认并记录快照。")
    if issue.requires_review:
        reasons.append("该 issue 标记为需要人工重点 Review。")
    return reasons
