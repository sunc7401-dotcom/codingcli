"""搜索结果模型 —— 对应 ``com.paicli.web.SearchResult`` record。"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass
class SearchResult:
    position: int
    title: str
    url: str
    snippet: str
    source: str = ""

    @classmethod
    def of(cls, position: int, title: str, url: str, snippet: str) -> SearchResult:
        """工厂方法：从 URL 自动推导 source。"""
        return cls(position=position, title=title, url=url, snippet=snippet, source=cls._extract_host(url))

    @staticmethod
    def _extract_host(url: str) -> str:
        """从 URL 提取主机名作为 source。"""
        try:
            parsed = urlparse(url)
            return parsed.hostname or "unknown"
        except Exception:
            return "unknown"

    @staticmethod
    def safe(title: str | None, url: str | None, snippet: str | None) -> SearchResult:
        """安全构造（处理 null 值）。"""
        return SearchResult(
            position=0,
            title=title or "",
            url=url or "",
            snippet=snippet or "",
        )
