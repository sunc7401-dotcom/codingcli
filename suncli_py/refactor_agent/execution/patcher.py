"""Patch generation and transactional application for refactor-agent apply."""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from suncli_py.refactor_agent.core.models import RefactoringType, RefactorIssue, RefactorPlan, SmellType
from suncli_py.refactor_agent.execution.patch_validator import AstPatchValidator

IGNORED_PARTS = {".git", "target", "build", ".gradle", "node_modules"}


class PatchError(Exception):
    """Raised when a refactor patch cannot be safely generated or applied."""


@dataclass(frozen=True)
class PatchChange:
    file_path: str
    before_text: str
    after_text: str
    description: str


@dataclass(frozen=True)
class PatchApplicationResult:
    patch_path: Path
    snapshot_path: Path
    diff_summary_path: Path
    changed_files: list[str]
    diff_text: str


class RefactorPatcher:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def generate_changes(
        self,
        plan: RefactorPlan,
        issue: RefactorIssue,
        *,
        llm_edit_plan: dict[str, Any] | None = None,
    ) -> list[PatchChange]:
        self._validate_plan(plan, issue)
        if llm_edit_plan:
            return self._changes_from_llm_edits(plan, llm_edit_plan)
        if issue.type == SmellType.DEAD_CODE and issue.suggested_refactoring == RefactoringType.REMOVE_DEAD_CODE:
            return [self._remove_dead_code(issue)]
        if issue.type == SmellType.LONG_METHOD and issue.suggested_refactoring == RefactoringType.EXTRACT_METHOD:
            return [self._extract_accumulator_method(issue)]
        raise PatchError("MVP only supports Remove Dead Code, controlled LLM edits, and conservative Extract Method.")

    def apply_changes(
        self,
        plan: RefactorPlan,
        changes: list[PatchChange],
        task_dir: Path,
    ) -> PatchApplicationResult:
        if not changes:
            raise PatchError("No patch changes to apply.")

        before_contents = {change.file_path: change.before_text for change in changes}
        resolved_paths = {change.file_path: self._resolve_allowed_file(change.file_path) for change in changes}
        snapshot_path = self._write_snapshot(plan, before_contents, resolved_paths, task_dir)
        diff_text = _format_unified_diff(changes)
        patch_path = task_dir / "patch.diff"
        diff_summary_path = task_dir / "diff_summary.txt"
        patch_path.write_text(diff_text, encoding="utf-8")

        written: list[Path] = []
        try:
            for change in changes:
                path = resolved_paths[change.file_path]
                path.write_text(change.after_text, encoding="utf-8")
                written.append(path)
            for change in changes:
                if resolved_paths[change.file_path].read_text(encoding="utf-8") != change.after_text:
                    raise PatchError(f"Re-read content did not match expected patch output: {change.file_path}")
            findings = AstPatchValidator(self.root).validate(plan, task_dir)
            if findings:
                raise PatchError("AST patch validation failed: " + "; ".join(findings))
        except Exception as err:
            for change in changes:
                path = resolved_paths[change.file_path]
                if path in written:
                    path.write_text(change.before_text, encoding="utf-8")
            if isinstance(err, PatchError):
                raise
            raise PatchError(f"Patch apply failed; restored files to pre-apply state: {err}") from err

        self._write_after_state(task_dir, resolved_paths)
        diff_summary_path.write_text(diff_text, encoding="utf-8")
        return PatchApplicationResult(
            patch_path=patch_path,
            snapshot_path=snapshot_path,
            diff_summary_path=diff_summary_path,
            changed_files=[change.file_path for change in changes],
            diff_text=diff_text,
        )

    def _validate_plan(self, plan: RefactorPlan, issue: RefactorIssue) -> None:
        planned_files = {_normalize_relative_path(file_path) for file_path in plan.files_to_modify}
        if not planned_files:
            raise PatchError("Plan does not include any allowed file.")
        issue_file = _normalize_relative_path(issue.file_path)
        if issue_file not in planned_files:
            raise PatchError(f"Patch target is outside planned files / 不在计划文件内: {issue.file_path}")
        for file_path in planned_files:
            self._resolve_allowed_file(file_path)

    def _remove_dead_code(self, issue: RefactorIssue) -> PatchChange:
        path = self._resolve_allowed_file(issue.file_path)
        original = path.read_text(encoding="utf-8")
        lines = original.splitlines(keepends=True)
        if issue.start_line < 1 or issue.end_line < issue.start_line or issue.end_line > len(lines):
            raise PatchError("Issue line range is outside the target file.")

        removed_text = "".join(lines[issue.start_line - 1 : issue.end_line])
        if "private" not in removed_text:
            raise PatchError("Target block does not contain a private marker; refusing automatic deletion.")
        updated = "".join(lines[: issue.start_line - 1] + lines[issue.end_line :])
        if updated == original:
            raise PatchError("Patch produced no changes.")
        return PatchChange(
            file_path=_normalize_relative_path(issue.file_path),
            before_text=original,
            after_text=updated,
            description=f"Remove dead private code: {issue.symbol or issue.file_path}",
        )

    def _changes_from_llm_edits(self, plan: RefactorPlan, edit_plan: dict[str, Any]) -> list[PatchChange]:
        planned = {_normalize_relative_path(file_path) for file_path in plan.files_to_modify}
        changes: list[PatchChange] = []
        for edit in edit_plan.get("edits", []):
            if not isinstance(edit, dict):
                continue
            file_path = _normalize_relative_path(str(edit.get("file_path", "")))
            if file_path not in planned:
                raise PatchError(f"LLM edit touches file outside plan: {file_path}")
            start_line = int(edit.get("start_line", 0))
            end_line = int(edit.get("end_line", 0))
            replacement = str(edit.get("replacement", ""))
            path = self._resolve_allowed_file(file_path)
            original = path.read_text(encoding="utf-8")
            lines = original.splitlines(keepends=True)
            if start_line < 1 or end_line < start_line or end_line > len(lines):
                raise PatchError(f"LLM edit line range is invalid: {file_path}:{start_line}-{end_line}")
            replacement_lines = replacement.splitlines(keepends=True)
            if replacement and not replacement.endswith(("\n", "\r")):
                replacement_lines[-1] += "\n"
            updated = "".join(lines[: start_line - 1] + replacement_lines + lines[end_line:])
            if updated != original:
                changes.append(
                    PatchChange(
                        file_path=file_path,
                        before_text=original,
                        after_text=updated,
                        description=str(edit_plan.get("explanation") or "LLM controlled edit operation"),
                    )
                )
        if not changes:
            raise PatchError("LLM did not return any usable edit operation.")
        return changes

    def _extract_accumulator_method(self, issue: RefactorIssue) -> PatchChange:
        path = self._resolve_allowed_file(issue.file_path)
        original = path.read_text(encoding="utf-8")
        lines = original.splitlines(keepends=True)
        if issue.start_line < 1 or issue.end_line > len(lines):
            raise PatchError("Extract Method issue line range is invalid.")

        method_lines = lines[issue.start_line - 1 : issue.end_line]
        return_var = _find_return_variable(method_lines)
        if not return_var:
            raise PatchError("Conservative Extract Method requires a simple `return variable;` method.")
        block_start, block_end = _find_accumulator_block(method_lines, return_var)
        if block_start is None or block_end is None:
            raise PatchError("No safe accumulator statement block found for Extract Method.")

        helper_name = _helper_name(issue.symbol or "extractedStep")
        absolute_start = issue.start_line - 1 + block_start
        absolute_end = issue.start_line - 1 + block_end
        block = lines[absolute_start : absolute_end + 1]
        indent = _leading_ws(block[0])
        method_indent = _leading_ws(lines[issue.start_line - 1])
        call_line = f"{indent}{return_var} = {helper_name}({return_var});\n"
        helper_lines = [
            "\n",
            f"{method_indent}private int {helper_name}(int {return_var}) {{\n",
            *block,
            f"{indent}return {return_var};\n",
            f"{method_indent}}}\n",
        ]
        updated_lines = lines[:absolute_start] + [call_line] + lines[absolute_end + 1 : issue.end_line]
        updated_lines += helper_lines + lines[issue.end_line :]
        return PatchChange(
            file_path=_normalize_relative_path(issue.file_path),
            before_text=original,
            after_text="".join(updated_lines),
            description=f"Extract accumulator block from {issue.symbol or issue.file_path}",
        )

    def _resolve_allowed_file(self, file_path: str) -> Path:
        relative = Path(_normalize_relative_path(file_path))
        if relative.is_absolute() or any(part in IGNORED_PARTS for part in relative.parts):
            raise PatchError(f"Path is not allowed for modification: {file_path}")
        path = (self.root / relative).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as err:
            raise PatchError(f"Planned file is outside project root: {file_path}") from err
        if not path.is_file():
            raise PatchError(f"Planned file does not exist: {file_path}")
        return path

    def _write_snapshot(
        self,
        plan: RefactorPlan,
        before_contents: dict[str, str],
        resolved_paths: dict[str, Path],
        task_dir: Path,
    ) -> Path:
        task_dir.mkdir(parents=True, exist_ok=True)
        before_dir = task_dir / "before"
        before_dir.mkdir(parents=True, exist_ok=True)
        for file_path, source_path in resolved_paths.items():
            destination = before_dir / file_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, destination)

        git_status = self._run_git(["git", "status", "--porcelain"])
        snapshot = {
            "task_id": plan.task_id,
            "issue_id": plan.issue_id,
            "head": self._run_git(["git", "rev-parse", "HEAD"]),
            "git_status": git_status,
            "planned_files": plan.files_to_modify,
            "user_changes_before_task": bool(git_status),
            "files": [
                {
                    "path": file_path,
                    "size": len(content),
                    "before_sha256": _sha256(content),
                    "before_copy": str((before_dir / file_path).relative_to(task_dir).as_posix()),
                }
                for file_path, content in before_contents.items()
            ],
        }
        snapshot_path = task_dir / "snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        return snapshot_path

    def _write_after_state(self, task_dir: Path, resolved_paths: dict[str, Path]) -> None:
        after_dir = task_dir / "after"
        after_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = task_dir / "snapshot.json"
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        after_by_path: dict[str, dict[str, str]] = {}
        for file_path, source_path in resolved_paths.items():
            destination = after_dir / file_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, destination)
            text = source_path.read_text(encoding="utf-8")
            after_by_path[file_path] = {
                "after_sha256": _sha256(text),
                "after_copy": str(destination.relative_to(task_dir).as_posix()),
            }
        for file_entry in snapshot.get("files", []):
            file_entry.update(after_by_path.get(file_entry.get("path"), {}))
        snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    def _run_git(self, command: list[str]) -> str | None:
        try:
            result = subprocess.run(
                command,
                cwd=str(self.root),
                capture_output=True,
                check=False,
                encoding="utf-8",
                errors="replace",
                text=True,
                timeout=15,
            )
        except (FileNotFoundError, OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip()


def _normalize_relative_path(file_path: str) -> str:
    return file_path.replace("\\", "/").strip().lstrip("/")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _format_unified_diff(changes: list[PatchChange]) -> str:
    chunks: list[str] = []
    for change in changes:
        before_lines = change.before_text.splitlines(keepends=True)
        after_lines = change.after_text.splitlines(keepends=True)
        chunks.extend(
            difflib.unified_diff(
                before_lines,
                after_lines,
                fromfile=f"a/{change.file_path}",
                tofile=f"b/{change.file_path}",
                lineterm="",
            )
        )
        chunks.append("")
    return "\n".join(chunks).rstrip() + "\n"


def _find_return_variable(lines: list[str]) -> str | None:
    for line in reversed(lines):
        match = re.match(r"\s*return\s+([A-Za-z_][A-Za-z0-9_]*)\s*;", line)
        if match:
            return match.group(1)
    return None


def _find_accumulator_block(lines: list[str], variable: str) -> tuple[int | None, int | None]:
    pattern = re.compile(rf"\s*{re.escape(variable)}\s*(?:[+\-*/]?=)\s*[^;]+;\s*$")
    spans: list[tuple[int, int]] = []
    start: int | None = None
    for index, line in enumerate(lines):
        if pattern.match(line):
            if start is None:
                start = index
        else:
            if start is not None and index - start >= 5:
                spans.append((start, index - 1))
            start = None
    if start is not None and len(lines) - start >= 5:
        spans.append((start, len(lines) - 1))
    return spans[0] if spans else (None, None)


def _helper_name(symbol: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "", symbol)
    if not cleaned:
        cleaned = "extractedStep"
    return "extracted" + cleaned[:1].upper() + cleaned[1:] + "Step"


def _leading_ws(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]
