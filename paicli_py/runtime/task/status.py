"""任务状态枚举。

对应 ``com.paicli.runtime.task.TaskStatus``。
"""

from enum import Enum


class TaskStatus(str, Enum):
    ENQUEUED = "enqueued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"

    @property
    def terminal(self) -> bool:
        """是否为终态。"""
        return self in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELED)

    @classmethod
    def from_string(cls, value: str) -> "TaskStatus":
        """从字符串解析任务状态（大小写不敏感）。"""
        try:
            return cls(value.lower())
        except ValueError:
            return cls.ENQUEUED
