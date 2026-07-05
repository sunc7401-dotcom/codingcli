"""执行计划 —— 包含一组有依赖关系的任务。

对应 ``com.paicli.plan.ExecutionPlan``。

特性：
- 基于拓扑排序的执行顺序计算
- 循环依赖检测
- 并行批次划分（get_execution_batches）
- 终端可视化（visualize / summarize）
"""

from __future__ import annotations

import time
from collections import OrderedDict
from enum import Enum

from paicli_py.plan.task import Task, TaskStatus


class PlanStatus(Enum):
    """计划状态。"""
    CREATED = "CREATED"        # 刚创建
    RUNNING = "RUNNING"        # 执行中
    COMPLETED = "COMPLETED"    # 全部完成
    FAILED = "FAILED"          # 有任务失败
    CANCELLED = "CANCELLED"    # 被取消


class ExecutionPlan:
    """有依赖关系的多任务执行计划。

    使用拓扑排序计算执行顺序，支持循环依赖检测和
    并行批次划分。
    """

    def __init__(self, id: str, goal: str) -> None:
        self.id = id
        self.goal = goal
        self.tasks: OrderedDict[str, Task] = OrderedDict()  # 保持插入顺序
        self.execution_order: list[str] = []
        self.status = PlanStatus.CREATED
        self.summary: str = ""
        self.start_time: float = 0.0
        self.end_time: float = 0.0

    # ── 任务管理 ──────────────────────────────────────────

    def add_task(self, task: Task) -> None:
        """添加任务并自动更新依赖关系。"""
        self.tasks[task.id] = task
        # 更新依赖关系：设置 dependents
        for dep_id in task.dependencies:
            dep = self.tasks.get(dep_id)
            if dep is not None:
                dep.add_dependent(task.id)

    def get_task(self, id: str) -> Task | None:
        return self.tasks.get(id)

    def get_all_tasks(self) -> list[Task]:
        return list(self.tasks.values())

    def get_root_tasks(self) -> list[Task]:
        """获取没有依赖的根任务。"""
        return [t for t in self.tasks.values() if not t.dependencies]

    def get_executable_tasks(self) -> list[Task]:
        """获取所有依赖都已完成的可执行任务。"""
        return [t for t in self.tasks.values() if t.is_executable(self.tasks)]

    # ── 拓扑排序 ──────────────────────────────────────────

    def compute_execution_order(self) -> bool:
        """计算拓扑排序执行顺序。

        Returns:
            True 表示成功，False 表示存在循环依赖。
        """
        self.execution_order.clear()
        visited: set[str] = set()
        visiting: set[str] = set()

        for task in self.tasks.values():
            if task.id not in visited:
                if not self._topological_sort(task, visited, visiting):
                    return False

        return True

    def _topological_sort(self, task: Task, visited: set[str], visiting: set[str]) -> bool:
        """DFS 拓扑排序（含环检测）。"""
        tid = task.id

        if tid in visiting:
            return False  # 有环
        if tid in visited:
            return True

        visiting.add(tid)

        for dep_id in task.dependencies:
            dep = self.tasks.get(dep_id)
            if dep is not None:
                if not self._topological_sort(dep, visited, visiting):
                    return False

        visiting.discard(tid)
        visited.add(tid)
        self.execution_order.append(tid)
        return True

    def get_execution_order(self) -> list[str]:
        """获取执行顺序（首次调用会自动计算）。"""
        if not self.execution_order:
            self.compute_execution_order()
        return list(self.execution_order)

    # ── 执行批次 ──────────────────────────────────────────

    def get_execution_batches(self) -> list[list[Task]]:
        """将任务按并行度划分为执行批次。

        每批中的所有任务可以并行执行（它们的依赖都已在前序批次中完成）。
        """
        if not self.tasks:
            return []

        remaining = OrderedDict(self.tasks)
        completed: set[str] = set()
        batches: list[list[Task]] = []

        while remaining:
            batch = [
                task for task in remaining.values()
                if completed.issuperset(task.dependencies)
            ]

            if not batch:
                break  # 无法继续（可能有环）

            batches.append(batch)
            for task in batch:
                del remaining[task.id]
                completed.add(task.id)

        return batches

    # ── 进度 ──────────────────────────────────────────────

    def get_progress(self) -> float:
        """获取执行进度（0.0 ~ 1.0）。"""
        if not self.tasks:
            return 1.0
        completed_count = sum(1 for t in self.tasks.values() if t.status == TaskStatus.COMPLETED)
        return completed_count / len(self.tasks)

    def is_all_completed(self) -> bool:
        return all(t.status == TaskStatus.COMPLETED for t in self.tasks.values())

    def has_failed(self) -> bool:
        return any(t.status == TaskStatus.FAILED for t in self.tasks.values())

    # ── 状态转换 ──────────────────────────────────────────

    def mark_started(self) -> None:
        self.status = PlanStatus.RUNNING
        self.start_time = time.time()

    def mark_completed(self) -> None:
        self.status = PlanStatus.COMPLETED
        self.end_time = time.time()

    def mark_failed(self) -> None:
        self.status = PlanStatus.FAILED
        self.end_time = time.time()

    @property
    def duration_ms(self) -> float:
        """获取总耗时（毫秒）。"""
        if self.start_time == 0.0:
            return 0.0
        end = self.end_time if self.end_time > 0 else time.time()
        return (end - self.start_time) * 1000

    # ── 可视化 ────────────────────────────────────────────

    @staticmethod
    def _status_icon(status: TaskStatus) -> str:
        return {
            TaskStatus.PENDING: "⏳",
            TaskStatus.RUNNING: "▶️",
            TaskStatus.COMPLETED: "✅",
            TaskStatus.FAILED: "❌",
            TaskStatus.SKIPPED: "⏭️",
        }.get(status, "?")

    def visualize(self) -> str:
        """终端可视化：带框线的完整计划展示。"""
        lines: list[str] = []

        goal_text = self.goal[:46] + "..." if len(self.goal) > 46 else self.goal
        lines.append("╔" + "═" * 58 + "╗")
        lines.append(f"║  执行计划: {goal_text:<46}║")
        lines.append("╠" + "═" * 58 + "╣")

        order = self.get_execution_order()
        for i, task_id in enumerate(order):
            task = self.tasks[task_id]
            icon = self._status_icon(task.status)
            deps = ", ".join(task.dependencies) if task.dependencies else "无"
            lines.append(
                f"║  {i + 1}. {icon} {task.id:<20} [{task.type.value:<10}] 依赖: {deps:<15}║"
            )
            desc = task.description[:50] + "..." if len(task.description) > 50 else task.description
            lines.append(f"║     {desc:<53}║")

        lines.append("╚" + "═" * 58 + "╝")
        lines.append(f"   进度: {self.get_progress() * 100:.0f}% | 状态: {self.status.value}")

        return "\n".join(lines)

    def summarize(self) -> str:
        """紧凑摘要（避免完整 DAG 占满终端）。"""
        batches = self.get_execution_batches()
        ready = self.get_executable_tasks()

        lines: list[str] = [
            "📋 计划摘要",
            f"   - 目标: {self._compact_goal(48)}",
            f"   - 任务数: {len(self.tasks)} | 并行批次: {len(batches)} | 当前可执行: {len(ready)} | 状态: {self.status.value}",
        ]

        if batches:
            first_batch_ids = [t.id for t in batches[0][:5]]
            more = f" 等 {len(batches[0])} 个任务" if len(batches[0]) > 5 else ""
            lines.append(f"   - 首批执行: {', '.join(first_batch_ids)}{more}")

            if len(batches) > 1:
                last = batches[-1]
                last_ids = [t.id for t in last[:5]]
                more2 = f" 等 {len(last)} 个任务" if len(last) > 5 else ""
                lines.append(f"   - 最终收敛: {', '.join(last_ids)}{more2}")

        return "\n".join(lines)

    def _compact_goal(self, max_len: int = 48) -> str:
        """将目标压缩为单行。"""
        single = " ".join(self.goal.replace("\r\n", " ").replace("\r", " ").replace("\n", " ").split())
        if len(single) <= max_len:
            return single
        return single[:max_len - 3] + "..."

    def __repr__(self) -> str:
        return f"ExecutionPlan[{self.id}: {self.goal}] ({len(self.tasks)} tasks, {self.status.value})"
