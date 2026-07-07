"""记忆系统协议。

对应 ``com.paicli.memory.Memory`` 接口。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from suncli_py.memory.memory_entry import MemoryEntry


@runtime_checkable
class Memory(Protocol):
    """记忆存储的通用协议（短期/长期）。"""

    def store(self, entry: MemoryEntry) -> None:
        """存入一条记忆。"""
        ...

    def retrieve(self, entry_id: str) -> MemoryEntry | None:
        """按 ID 检索。"""
        ...

    def search(self, query: str, limit: int) -> list[MemoryEntry]:
        """关键词搜索。"""
        ...

    def get_all(self) -> list[MemoryEntry]:
        """获取全部条目。"""
        ...

    def delete(self, entry_id: str) -> bool:
        """删除一条记忆。"""
        ...

    def clear(self) -> None:
        """清空全部记忆。"""
        ...

    @property
    def token_count(self) -> int:
        """当前 token 占用。"""
        ...

    def size(self) -> int:
        """条目数量。"""
        ...
