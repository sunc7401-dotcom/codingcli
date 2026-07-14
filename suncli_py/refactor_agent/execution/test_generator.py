"""Candidate characterization test generation."""

from __future__ import annotations

import re
from pathlib import Path

from suncli_py.refactor_agent.core.models import CharacterizationTestPlan, RefactorIssue, RefactorPlan


class CharacterizationTestGenerator:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def create_plan(self, plan: RefactorPlan, issue: RefactorIssue) -> CharacterizationTestPlan:
        source_path = self.root / issue.file_path
        source_text = source_path.read_text(encoding="utf-8", errors="replace")
        package_name = _package_name(source_text)
        class_name = Path(issue.file_path).stem
        test_class_name = f"{class_name}CharacterizationTest"
        destination = _destination_file(issue.file_path, test_class_name)
        target_method = issue.symbol or class_name
        content = _test_content(package_name, test_class_name, class_name, target_method)
        return CharacterizationTestPlan(
            issue_id=issue.id,
            target_class=class_name,
            target_methods=[target_method],
            test_framework="plain-java-skeleton",
            destination_file=destination,
            assertion_intent=[
                f"锁定 {class_name} 当前可构造性，作为人工补充断言的起点。",
                f"请在应用重构前补充 {target_method} 的典型输入、边界输入和异常分支断言。",
            ],
            content=content,
        )


def _package_name(source_text: str) -> str | None:
    match = re.search(r"^\s*package\s+([A-Za-z_][A-Za-z0-9_.]*)\s*;", source_text, re.MULTILINE)
    return match.group(1) if match else None


def _destination_file(source_file: str, test_class_name: str) -> str:
    path = Path(source_file)
    parts = list(path.parts)
    if "main" in parts:
        parts[parts.index("main")] = "test"
    parts[-1] = f"{test_class_name}.java"
    return Path(*parts).as_posix()


def _test_content(package_name: str | None, test_class_name: str, class_name: str, target_method: str) -> str:
    package_line = f"package {package_name};\n\n" if package_name else ""
    return (
        f"{package_line}"
        f"class {test_class_name} {{\n"
        f"    void characterize_{target_method}_currentBehavior() {{\n"
        f"        new {class_name}();\n"
        f"    }}\n"
        f"}}\n"
    )
