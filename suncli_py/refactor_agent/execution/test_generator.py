"""Candidate characterization test generation."""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from suncli_py.refactor_agent.core.models import CharacterizationTestPlan, RefactorIssue, RefactorPlan


class TestGenerationError(Exception):
    """Raised when an LLM-generated test violates controlled-write policy."""


@dataclass(frozen=True)
class GeneratedTestApplication:
    test_files: list[str]
    patch_path: Path
    diff_text: str


class GeneratedTestFileManager:
    """Allow an agent to create only new, meaningful tests for one target source file."""

    def __init__(
        self,
        root: str | Path,
        issue: RefactorIssue,
        task_dir: Path,
        artifact_dir: Path,
    ) -> None:
        self.root = Path(root).resolve()
        self.issue = issue
        self.task_dir = task_dir
        self.artifact_dir = artifact_dir
        self.allowed_files = generated_test_candidates(issue.file_path)
        self._created: dict[str, str] = {}
        self.application: GeneratedTestApplication | None = None

    def apply(self, files: Any) -> GeneratedTestApplication:
        if not isinstance(files, list) or not files or len(files) > 4:
            raise TestGenerationError("files must contain between one and four generated tests")

        proposed: dict[str, str] = {}
        for entry in files:
            if not isinstance(entry, dict):
                raise TestGenerationError("each generated test must be an object")
            file_path = _normalize_test_path(str(entry.get("file_path") or ""))
            content = str(entry.get("content") or "")
            if file_path in proposed:
                raise TestGenerationError(f"duplicate generated test path: {file_path}")
            self._validate_path(file_path)
            _validate_test_content(content, Path(self.issue.file_path).stem)
            proposed[file_path] = content

        previous = dict(self._created)
        try:
            for file_path in previous.keys() - proposed.keys():
                path = self._resolve(file_path)
                if path.is_file():
                    path.unlink()
            for file_path, content in proposed.items():
                path = self._resolve(file_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            self._created = proposed
            self.application = self._write_artifacts()
            return self.application
        except Exception as err:
            for file_path in proposed:
                path = self._resolve(file_path)
                if path.is_file():
                    path.unlink()
            for file_path, content in previous.items():
                path = self._resolve(file_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            self._created = previous
            if isinstance(err, TestGenerationError):
                raise
            raise TestGenerationError(f"failed to write generated tests transactionally: {err}") from err

    def _validate_path(self, file_path: str) -> None:
        if file_path not in self.allowed_files:
            raise TestGenerationError(
                f"generated test path is outside the deterministic allowlist: {file_path}; "
                f"allowed={self.allowed_files}"
            )
        path = self._resolve(file_path)
        if path.exists() and file_path not in self._created:
            raise TestGenerationError(f"refusing to overwrite an existing test: {file_path}")

    def _resolve(self, file_path: str) -> Path:
        path = (self.root / file_path).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as err:
            raise TestGenerationError(f"generated test path escapes project root: {file_path}") from err
        return path

    def _write_artifacts(self) -> GeneratedTestApplication:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        chunks: list[str] = []
        state_files: list[dict[str, str]] = []
        for file_path, content in sorted(self._created.items()):
            chunks.extend(
                difflib.unified_diff(
                    [],
                    content.splitlines(keepends=True),
                    fromfile="/dev/null",
                    tofile=f"b/{file_path}",
                    lineterm="",
                )
            )
            chunks.append("")
            state_files.append(
                {
                    "path": file_path,
                    "generated_sha256": hashlib.sha256(self._resolve(file_path).read_bytes()).hexdigest(),
                }
            )
        diff_text = "\n".join(chunks).rstrip() + "\n"
        patch_path = self.artifact_dir / "test.patch.diff"
        patch_path.write_text(diff_text, encoding="utf-8")
        (self.task_dir / "test.patch.diff").write_text(diff_text, encoding="utf-8")
        state = {"files": state_files, "patch": str(patch_path.relative_to(self.task_dir).as_posix())}
        (self.task_dir / "generated_test_files.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return GeneratedTestApplication(sorted(self._created), patch_path, diff_text)


def generated_test_candidates(source_file: str) -> list[str]:
    normalized = _normalize_test_path(source_file)
    marker = "/src/main/java/"
    padded = "/" + normalized
    if marker not in padded:
        raise TestGenerationError("target source is not under src/main/java")
    test_source = padded.replace(marker, "/src/test/java/", 1).lstrip("/")
    path = Path(test_source)
    stem = path.stem
    return [
        (path.parent / f"{stem}CharacterizationTest.java").as_posix(),
        (path.parent / f"{stem}RefactorGuardTest.java").as_posix(),
    ]


def _normalize_test_path(file_path: str) -> str:
    normalized = file_path.replace("\\", "/").strip()
    if not normalized or normalized.startswith("/") or normalized.startswith("../") or "/../" in normalized:
        raise TestGenerationError(f"invalid generated test path: {file_path}")
    return normalized


def _validate_test_content(content: str, target_class: str) -> None:
    if not content.strip() or len(content) > 100_000:
        raise TestGenerationError("generated test content is empty or too large")
    if target_class not in content:
        raise TestGenerationError(f"generated test does not exercise target class {target_class}")
    if "@Test" not in content:
        raise TestGenerationError("generated test must contain at least one @Test method")
    lowered = re.sub(r"\s+", "", content).lower()
    forbidden = ("@disabled", "@ignore", "asserttrue(true)", "assertfalse(false)")
    if any(marker in lowered for marker in forbidden):
        raise TestGenerationError("disabled or constant/trivial assertions are forbidden")
    assertion_patterns = (
        r"\bassertEquals\s*\(",
        r"\bassertTrue\s*\(",
        r"\bassertFalse\s*\(",
        r"\bassertThat\s*\(",
        r"\bassertThrows\s*\(",
        r"\bassert[A-Z][A-Za-z0-9_]*\s*\(",
        r"\bverify\s*\(",
    )
    if not any(re.search(pattern, content) for pattern in assertion_patterns):
        raise TestGenerationError("generated test must contain an observable assertion or mock verification")


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
