"""Task-level rollback for refactor-agent snapshots."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from suncli_py.refactor_agent.models import RollbackResult


class RollbackError(Exception):
    """Raised when rollback cannot be performed safely."""


class TaskRollbacker:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def rollback(self, task_dir: Path, *, force: bool = False) -> RollbackResult:
        snapshot_path = task_dir / "snapshot.json"
        if not snapshot_path.is_file():
            raise RollbackError("未找到 snapshot.json，无法回滚。")
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        conflicts = self._detect_conflicts(task_dir, snapshot)
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

        return RollbackResult(
            status="rolled_back",
            task_id=snapshot.get("task_id", task_dir.name),
            restored_files=restored,
            conflicts=conflicts,
            message="已恢复任务开始前的计划文件内容。",
        )

    def _detect_conflicts(self, task_dir: Path, snapshot: dict) -> list[str]:
        conflicts: list[str] = []
        for file_entry in snapshot.get("files", []):
            after_sha = file_entry.get("after_sha256")
            if not after_sha:
                continue
            current_path = (self.root / file_entry["path"]).resolve()
            if not current_path.is_file():
                conflicts.append(file_entry["path"])
                continue
            if _file_sha256(current_path) != after_sha:
                conflicts.append(file_entry["path"])
        return conflicts


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
