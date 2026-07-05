"""任务节点 —— 表示一个可执行的任务单元。

对应 ``com.paicli.plan.Task``。
"""

from __future__ import annotations

import time
from enum import Enum


class TaskType(Enum):
    """任务类型。"""
    PLANNING = "PLANNING"          # 规划任务
    FILE_READ = "FILE_READ"        # 读取文件
    FILE_WRITE = "FILE_WRITE"      # 写入文件
    COMMAND = "COMMAND"            # 执行命令
    ANALYSIS = "ANALYSIS"          # 分析结果
    VERIFICATION = "VERIFICATION"  # 验证结果


class TaskStatus(Enum):
    """任务状态。"""
    PENDING = "PENDING"        # 等待执行
    RUNNING = "RUNNING"        # 执行中
    COMPLETED = "COMPLETED"    # 已完成
    FAILED = "FAILED"          # 失败
    SKIPPED = "SKIPPED"        # 跳过


class Task:
    """执行计划中的一个可执行任务单元。

    维护自身的状态、依赖关系和执行耗时。
    通过 ``is_executable()`` 判断是否满足依赖条件可执行。
    """

    def __init__(
        self,
        id: str,
        description: str,
        type: TaskType,
        dependencies: list[str] | None = None,
    ) -> None:
        self.id = id
        self.description = description
        self.type = type
        self.status = TaskStatus.PENDING
        self.result: str | None = None
        self.error: str | None = None
        self.dependencies: list[str] = list(dependencies) if dependencies else []
        self.dependents: list[str] = []  # 依赖此任务的其他任务 ID
        self.start_time: float = 0.0
        self.end_time: float = 0.0

    # ── 依赖管理 ──────────────────────────────────────────

    def add_dependency(self, task_id: str) -> None:
        """添加此任务依赖的前置任务 ID。"""
        if task_id not in self.dependencies:
            self.dependencies.append(task_id)

    def add_dependent(self, task_id: str) -> None:
        """添加依赖此任务的后置任务 ID。"""
        if task_id not in self.dependents:
            self.dependents.append(task_id)

    # ── 状态转换 ──────────────────────────────────────────

    def mark_started(self) -> None:
        """标记为执行中。"""
        self.status = TaskStatus.RUNNING
        self.start_time = time.time()

    def mark_completed(self, result: str) -> None:
        """标记为已完成。"""
        self.status = TaskStatus.COMPLETED
        self.result = result
        self.end_time = time.time()

    def mark_failed(self, error: str) -> None:
        """标记为失败。"""
        self.status = TaskStatus.FAILED
        self.error = error
        self.end_time = time.time()

    def mark_skipped(self) -> None:
        """标记为跳过。"""
        self.status = TaskStatus.SKIPPED
        self.end_time = time.time()

    # ── 查询 ──────────────────────────────────────────────

    @property
    def duration_ms(self) -> float:
        """获取执行耗时（毫秒）。"""
        if self.start_time == 0.0:
            return 0.0
        end = self.end_time if self.end_time > 0 else time.time()
        return (end - self.start_time) * 1000

    def is_executable(self, all_tasks: dict[str, Task]) -> bool:
        """检查是否可以执行（所有依赖都已完成）。

        Args:
            all_tasks: 全部任务的字典 {id: Task}
        """
        if self.status != TaskStatus.PENDING:
            return False
        for dep_id in self.dependencies:
            dep = all_tasks.get(dep_id)
            if dep is None or dep.status != TaskStatus.COMPLETED:
                return False
        return True

    def __repr__(self) -> str:
        return f"Task[{self.id}: {self.description}] ({self.status.value})"
