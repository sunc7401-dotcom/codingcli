"""快照服务 —— 对应 ``com.paicli.snapshot.SnapshotService``。"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from loguru import logger

from paicli_py.snapshot.config import SnapshotConfig
from paicli_py.snapshot.restore_result import RestoreResult
from paicli_py.snapshot.side_git import SideGitManager
from paicli_py.snapshot.turn_snapshot import TurnSnapshot


class SnapshotService:
    def __init__(self, project_path: str) -> None:
        self._config = SnapshotConfig
        self._git_manager = SideGitManager(project_path)
        self._enabled = self._config.enabled()
        self._turn_counter = 0
        self._last_async_task: Any = None

    @classmethod
    def for_project(cls, project_path: str) -> SnapshotService:
        return cls(project_path)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def close(self) -> None:
        self._git_manager.close()

    # ── 快照操作 ─────────────────────────────────────────

    async def snapshot_before_turn(self) -> TurnSnapshot | None:
        if not self._enabled: return None
        self._turn_counter += 1
        return self._git_manager.pre_turn_snapshot(f"turn-{self._turn_counter}")

    async def snapshot_after_turn(self) -> TurnSnapshot | None:
        if not self._enabled: return None
        return self._git_manager.post_turn_snapshot(f"turn-{self._turn_counter}")

    async def restore(self, turn_index: int = -1) -> RestoreResult:
        if not self._enabled:
            return RestoreResult(success=False, error="快照功能未启用")
        return self._git_manager.restore_pre_turn(turn_index)

    # ── 托管执行 ─────────────────────────────────────────

    async def run_turn(self, mode: str, input_text: str, supplier: Callable[[], Any]) -> Any:
        """包裹一次 Agent 轮次执行。

        对应 Java: <T> T runTurn(String mode, String input, ThrowingSupplier<T> supplier)
        """
        turn_id = f"{mode}-{int(time.time() * 1000)}"
        summary = input_text[:120].replace("\n", " ")

        self._git_manager.pre_turn_snapshot(turn_id, summary)
        try:
            result = supplier()
            self._last_async_task = asyncio.create_task(self._async_post_snapshot(turn_id, summary))
            return result
        except Exception:
            self._last_async_task = asyncio.create_task(self._async_post_snapshot(turn_id, summary))
            raise

    async def _async_post_snapshot(self, turn_id: str, summary: str) -> None:
        try:
            self._git_manager.post_turn_snapshot(turn_id, summary)
        except Exception as e:
            logger.warning(f"后置快照失败: {e}")

    # ── 查询 / 管理 ──────────────────────────────────────

    def list_snapshots(self, limit: int = 50) -> list[TurnSnapshot]:
        return self._git_manager.list_snapshots(limit)

    def status(self) -> str:
        return self._git_manager.format_status()

    def clean(self) -> str:
        """清理所有快照，返回状态消息。"""
        return self._git_manager.clean_snapshots()

    async def await_idle(self) -> None:
        """等待异步后置快照任务完成（最长 60 秒）。"""
        if self._last_async_task:
            try:
                await asyncio.wait_for(self._last_async_task, timeout=60)
            except TimeoutError:
                logger.warning("等待后置快照超时 (60s)")

    @property
    def manager(self) -> SideGitManager:
        return self._git_manager
