"""搜索提供商协议 + SearchResult 模型。

对应 ``com.paicli.web.SearchProvider`` 接口和 ``SearchResult`` record。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class SearchResult:
    """单条搜索结果。"""
    position: int
    title: str
    url: str
    snippet: str
    source: str = ""

    @classmethod
    def of(cls, position: int, title: str, url: str, snippet: str, source: str = "") -> SearchResult:
        return cls(position=position, title=title, url=url, snippet=snippet, source=source)


@runtime_checkable
class SearchProvider(Protocol):
    """Web 搜索协议。"""

    @property
    def name(self) -> str:
        """提供商名称。"""
        return "unknown"

    def is_ready(self) -> bool:
        """是否可用。"""
        return False

    def unavailable_hint(self) -> str:
        """不可用时的提示信息。"""
        return f"搜索提供商 {self.name} 未配置"

    async def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """执行搜索。"""
        ...
