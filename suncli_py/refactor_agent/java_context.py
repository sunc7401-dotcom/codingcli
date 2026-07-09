"""Context collection for refactor planning."""

from __future__ import annotations

from pathlib import Path

from suncli_py.refactor_agent.java_ast import JavaAstError, JavaParserAnalyzer
from suncli_py.refactor_agent.models import JavaContext, RefactorIssue

IGNORED_DIRS = {".git", ".paicli", "target", "build", ".gradle", "node_modules"}


class JavaContextCollector:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def collect(self, issue: RefactorIssue) -> JavaContext:
        warnings: list[str] = []
        target_path = (self.root / issue.file_path).resolve()
        try:
            target_path.relative_to(self.root)
        except ValueError:
            warnings.append(f"目标文件越界，无法收集上下文: {issue.file_path}")
            return JavaContext(issue.id, issue.file_path, issue.symbol, "", [], [], warnings)

        lines = target_path.read_text(encoding="utf-8", errors="replace").splitlines()
        source_excerpt = _source_excerpt(lines, issue.start_line, issue.end_line)
        related_tests = self._find_related_tests(issue.file_path)
        direct_callers = self._find_direct_callers(issue)

        return JavaContext(
            issue_id=issue.id,
            target_file=issue.file_path,
            target_symbol=issue.symbol,
            source_excerpt=source_excerpt,
            related_tests=related_tests,
            direct_callers=direct_callers,
            warnings=warnings,
        )

    def _find_related_tests(self, file_path: str) -> list[str]:
        path = Path(file_path)
        parts = path.parts
        if "src" not in parts or "main" not in parts or "java" not in parts:
            return []

        class_name = path.stem
        java_index = parts.index("java")
        package_parts = parts[java_index + 1 : -1]
        test_base = self.root / "src" / "test" / "java" / Path(*package_parts)
        candidates = [
            test_base / f"{class_name}Test.java",
            test_base / f"{class_name}Tests.java",
            test_base / f"{class_name}IT.java",
        ]
        related = []
        for candidate in candidates:
            if candidate.is_file():
                related.append(candidate.relative_to(self.root).as_posix())
        return related

    def _find_direct_callers(self, issue: RefactorIssue) -> list[str]:
        if not issue.symbol:
            return []

        symbol_callers = self._find_direct_callers_with_symbols(issue)
        if symbol_callers:
            return symbol_callers

        callers: list[str] = []
        needle = f"{issue.symbol}("
        for path in sorted(self.root.rglob("*.java")):
            relative = path.relative_to(self.root)
            if any(part in IGNORED_DIRS for part in relative.parts):
                continue
            relative_text = relative.as_posix()
            if relative_text == issue.file_path:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if needle in text:
                callers.append(relative_text)
            if len(callers) >= 20:
                break
        return callers

    def _find_direct_callers_with_symbols(self, issue: RefactorIssue) -> list[str]:
        java_files = [
            path
            for path in sorted(self.root.rglob("*.java"))
            if not any(part in IGNORED_DIRS for part in path.relative_to(self.root).parts)
        ]
        try:
            analyses = JavaParserAnalyzer(self.root).analyze_files(java_files)
        except JavaAstError:
            return []

        callers: list[str] = []
        for analysis in analyses:
            if analysis.relative_path == issue.file_path:
                continue
            for call in analysis.method_calls:
                if call.name == issue.symbol and call.symbol_resolved:
                    callers.append(analysis.relative_path)
                    break
            if len(callers) >= 20:
                break
        return callers


def _source_excerpt(lines: list[str], start_line: int, end_line: int) -> str:
    start_index = max(start_line - 4, 0)
    end_index = min(end_line + 3, len(lines))
    excerpt_lines = []
    for line_number, text in enumerate(lines[start_index:end_index], start=start_index + 1):
        excerpt_lines.append(f"{line_number:>4}: {text}")
    return "\n".join(excerpt_lines)
