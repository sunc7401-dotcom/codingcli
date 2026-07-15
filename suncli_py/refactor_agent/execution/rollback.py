"""Task-level rollback for refactor-agent snapshots."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from suncli_py.refactor_agent.core.models import RollbackResult


class RollbackError(Exception):
    """Raised when rollback cannot be performed safely."""


class TaskRollbacker:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def rollback(
        self,
        task_dir: Path,
        *,
        force: bool = False,
        preserve_generated_tests: bool = False,
    ) -> RollbackResult:
        snapshot_path = task_dir / "snapshot.json"
        if not snapshot_path.is_file():
            raise RollbackError("未找到 snapshot.json，无法回滚。")
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        after_state_path = task_dir / "after_state.json"
        after_state = (
            json.loads(after_state_path.read_text(encoding="utf-8"))
            if after_state_path.is_file()
            else {}
        )
        generated_tests = self._generated_test_entries(task_dir)
        conflicts = self._detect_conflicts(
            snapshot,
            after_state,
            [] if preserve_generated_tests else generated_tests,
        )
        if conflicts and not force:
            return RollbackResult(
                status="conflict",
                task_id=snapshot.get("task_id", task_dir.name),
                restored_files=[],
                conflicts=conflicts,
                message="检测到任务后同文件存在新修改，未执行回滚。",
            )

        restored: list[str] = []
        for file_entry in snapshot.get("files", []):
            relative_path = file_entry["path"]
            before_copy = task_dir / file_entry["before_copy"]
            destination = (self.root / relative_path).resolve()
            try:
                destination.relative_to(self.root)
            except ValueError as err:
                raise RollbackError(f"快照路径越界: {relative_path}") from err
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(before_copy, destination)
            restored.append(relative_path)

        if not preserve_generated_tests:
            for entry in generated_tests:
                relative_path = str(entry.get("path") or "")
                destination = self._safe_destination(relative_path)
                if destination.is_file():
                    destination.unlink()
                restored.append(relative_path)

        return RollbackResult(
            status="rolled_back",
            task_id=snapshot.get("task_id", task_dir.name),
            restored_files=restored,
            conflicts=conflicts,
            message="已恢复任务开始前的计划文件内容。",
        )

    def generated_test_conflicts(self, task_dir: Path) -> list[str]:
        """Return generated guards whose current content differs from the recorded version."""
        return self._detect_generated_test_conflicts(self._generated_test_entries(task_dir))

    def _detect_conflicts(
        self,
        snapshot: dict[str, Any],
        after_state: dict[str, Any],
        generated_tests: list[dict[str, Any]],
    ) -> list[str]:
        conflicts: list[str] = []
        after_by_path = {
            entry.get("path"): entry.get("after_sha256")
            for entry in after_state.get("files", [])
            if isinstance(entry, dict)
        }
        for file_entry in snapshot.get("files", []):
            after_sha = after_by_path.get(file_entry.get("path")) or file_entry.get("after_sha256")
            if not after_sha:
                continue
            current_path = (self.root / file_entry["path"]).resolve()
            if not current_path.is_file():
                conflicts.append(file_entry["path"])
                continue
            if _file_sha256(current_path) != after_sha:
                conflicts.append(file_entry["path"])
        conflicts.extend(self._detect_generated_test_conflicts(generated_tests))
        return conflicts

    def _detect_generated_test_conflicts(self, generated_tests: list[dict[str, Any]]) -> list[str]:
        conflicts: list[str] = []
        for entry in generated_tests:
            relative_path = str(entry.get("path") or "")
            expected_sha = str(entry.get("generated_sha256") or "")
            current_path = self._safe_destination(relative_path)
            if not expected_sha or not current_path.is_file() or _file_sha256(current_path) != expected_sha:
                conflicts.append(relative_path)
        return conflicts

    def _generated_test_entries(self, task_dir: Path) -> list[dict[str, Any]]:
        state_path = task_dir / "generated_test_files.json"
        if not state_path.is_file():
            return []
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as err:
            raise RollbackError(f"无法读取生成测试清单: {err}") from err
        files = state.get("files", [])
        if not isinstance(files, list):
            raise RollbackError("生成测试清单格式错误")
        return [entry for entry in files if isinstance(entry, dict)]

    def _safe_destination(self, relative_path: str) -> Path:
        if not relative_path:
            raise RollbackError("生成测试清单包含空路径")
        destination = (self.root / relative_path).resolve()
        try:
            destination.relative_to(self.root)
        except ValueError as err:
            raise RollbackError(f"生成测试路径越界: {relative_path}") from err
        return destination


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
