"""任务执行器协议。

对应 ``com.paicli.runtime.task.TaskRunner``。
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class TaskRunner(Protocol):
    """后台任务执行器协议。"""
    async def run(self, prompt: str) -> str:
        """执行任务并返回结果。"""
        ...
