"""任务执行器协议 —— 对应 com.paicli.runtime.task.TaskRunner。"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class TaskRunner(Protocol):
    def run(self, prompt: str) -> str:
        """执行任务并返回结果。"""
        ...
