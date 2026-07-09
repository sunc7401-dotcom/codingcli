"""AST-level validation after a refactor patch is written."""

from __future__ import annotations

from pathlib import Path

from suncli_py.refactor_agent.java_ast import AstFileAnalysis, JavaAstError, JavaParserAnalyzer
from suncli_py.refactor_agent.models import RefactorPlan


class AstPatchValidator:
    """Validate patched Java files with JavaParser and stable public structure checks."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def validate(self, plan: RefactorPlan, task_dir: Path) -> list[str]:
        findings: list[str] = []
        before_root = task_dir / "before"
        for file_path in _planned_java_files(plan):
            before_file = before_root / file_path
            current_file = self.root / file_path
            if not before_file.is_file():
                findings.append(f"Missing before snapshot for AST validation: {file_path}")
                continue
            if not current_file.is_file():
                findings.append(f"Patched Java file is missing: {file_path}")
                continue

            before = self._analyze_one(before_root, before_file, file_path)
            current = self._analyze_one(self.root, current_file, file_path)
            if isinstance(before, str):
                findings.append(before)
                continue
            if isinstance(current, str):
                findings.append(current)
                continue

            findings.extend(_compare_ast_shape(file_path, before, current))
        return findings

    @staticmethod
    def _analyze_one(root: Path, source: Path, file_path: str) -> AstFileAnalysis | str:
        try:
            analyses = JavaParserAnalyzer(root).analyze_files([source])
        except JavaAstError as err:
            return f"JavaParser validation failed for {file_path}: {err}"
        if not analyses:
            return f"JavaParser returned no AST for {file_path}"
        return analyses[0]


def _planned_java_files(plan: RefactorPlan) -> list[Path]:
    return [
        Path(file_path.replace("\\", "/").lstrip("/"))
        for file_path in plan.files_to_modify
        if file_path.replace("\\", "/").endswith(".java")
    ]


def _compare_ast_shape(file_path: Path, before: AstFileAnalysis, current: AstFileAnalysis) -> list[str]:
    findings: list[str] = []
    before_classes = sorted((item.kind, item.name) for item in before.classes)
    current_classes = sorted((item.kind, item.name) for item in current.classes)
    if before_classes != current_classes:
        findings.append(
            f"Class declarations changed unexpectedly in {file_path}: "
            f"before={before_classes}, after={current_classes}"
        )

    before_api = _externally_visible_signatures(before)
    current_api = _externally_visible_signatures(current)
    if before_api != current_api:
        removed = sorted(before_api - current_api)
        added = sorted(current_api - before_api)
        findings.append(
            f"Non-private method signatures changed unexpectedly in {file_path}: "
            f"removed={removed}, added={added}"
        )
    return findings


def _externally_visible_signatures(analysis: AstFileAnalysis) -> set[str]:
    return {method.signature for method in analysis.methods if not method.is_private}
