from __future__ import annotations

from pathlib import Path

import pytest

from suncli_py.refactor_agent.analysis.java_ast import AstFileAnalysis, AstMethodCall, JavaParserAnalyzer
from suncli_py.refactor_agent.analysis.java_context import JavaContextCollector
from suncli_py.refactor_agent.core.models import (
    RefactoringType,
    RefactorIssue,
    RiskLevel,
    Severity,
    SmellType,
)


def test_context_collector_reuses_scan_ast_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue, caller_analysis = _issue_and_caller_analysis(tmp_path)

    def fail_if_reparsed(*args, **kwargs):
        del args, kwargs
        raise AssertionError("JavaParser should not run when a scan AST snapshot is available")

    monkeypatch.setattr(JavaParserAnalyzer, "analyze_files", fail_if_reparsed)

    context = JavaContextCollector(tmp_path, ast_analyses=[caller_analysis]).collect(issue)

    assert context.direct_callers == ["src/main/java/demo/OrderService.java"]


def test_context_collector_analyzes_files_without_scan_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue, caller_analysis = _issue_and_caller_analysis(tmp_path)
    calls = 0

    def analyze_files(self, paths):
        nonlocal calls
        del self, paths
        calls += 1
        return [caller_analysis]

    monkeypatch.setattr(JavaParserAnalyzer, "analyze_files", analyze_files)

    context = JavaContextCollector(tmp_path).collect(issue)

    assert calls == 1
    assert context.direct_callers == ["src/main/java/demo/OrderService.java"]


def _issue_and_caller_analysis(tmp_path: Path) -> tuple[RefactorIssue, AstFileAnalysis]:
    source_dir = tmp_path / "src" / "main" / "java" / "demo"
    source_dir.mkdir(parents=True)
    target_path = source_dir / "Customer.java"
    caller_path = source_dir / "OrderService.java"
    target_path.write_text("class Customer { int score() { return 1; } }\n", encoding="utf-8")
    caller_path.write_text("class OrderService { int total() { return customer.score(); } }\n", encoding="utf-8")

    issue = RefactorIssue(
        id="RA-0001",
        type=SmellType.LONG_METHOD,
        severity=Severity.MEDIUM,
        file_path="src/main/java/demo/Customer.java",
        symbol="score",
        start_line=1,
        end_line=1,
        evidence=[],
        impact="test impact",
        recommendation="test recommendation",
        suggested_refactoring=RefactoringType.EXTRACT_METHOD,
        risk_level=RiskLevel.MEDIUM,
    )
    caller_analysis = AstFileAnalysis(
        path=caller_path,
        relative_path="src/main/java/demo/OrderService.java",
        methods=[],
        classes=[],
        method_calls=[
            AstMethodCall(
                name="score",
                start_line=1,
                end_line=1,
                scope="customer",
                declaring_type="demo.Customer",
                resolved_signature="demo.Customer.score()",
                return_type="int",
                symbol_resolved=True,
                error="",
            )
        ],
        field_accesses=[],
    )
    return issue, caller_analysis
