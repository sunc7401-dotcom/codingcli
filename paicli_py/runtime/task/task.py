"""持久化任务模型。

对应 ``com.paicli.runtime.task.DurableTask``。
"""

from __future__ import annotations

from dataclasses import dataclass

from paicli_py.runtime.task.status import TaskStatus


@dataclass
class DurableTask:
    """持久化任务记录。"""
    id: str
    status: TaskStatus = TaskStatus.ENQUEUED
    prompt: str = ""
    result: str | None = None
    error: str | None = None
    created_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int = 0

    @property
    def terminal(self) -> bool:
        return self.status.terminal

    @property
    def short_prompt(self) -> str:
        """单行截断 prompt（80 字符）。"""
        line = self.prompt.replace("\n", " ").strip()
        return line[:77] + "..." if len(line) > 80 else line
