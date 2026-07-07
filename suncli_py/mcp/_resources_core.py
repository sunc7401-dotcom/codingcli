"""MCP 资源缓存。

对应 ``com.paicli.mcp.resources`` 包。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from suncli_py.mcp.protocol import McpResourceDescriptor


@dataclass
class CachedResource:
    descriptor: McpResourceDescriptor
    cached_at: float = field(default_factory=time.time)

    @property
    def age_seconds(self) -> float:
        return time.time() - self.cached_at


class McpResourceCache:
    """MCP 资源描述符的 TTL 缓存。

    按服务器分组，支持过期失效。
    """

    DEFAULT_TTL = 300  # 5 分钟

    def __init__(self, ttl: int = DEFAULT_TTL) -> None:
        self._ttl = ttl
        self._cache: dict[str, list[CachedResource]] = {}  # server_name → resources

    def update(self, server_name: str, resources: list[McpResourceDescriptor]) -> None:
        """更新一个服务器的资源列表。"""
        now = time.time()
        self._cache[server_name] = [
            CachedResource(descriptor=r, cached_at=now) for r in resources
        ]

    def get_all(self) -> list[McpResourceDescriptor]:
        """获取所有未过期的资源。"""
        now = time.time()
        result: list[McpResourceDescriptor] = []
        for _server_name, cached_list in self._cache.items():
            for cr in cached_list:
                if now - cr.cached_at < self._ttl:
                    result.append(cr.descriptor)
        return result

    def get_by_server(self, server_name: str) -> list[McpResourceDescriptor]:
        """按服务器名获取资源。"""
        now = time.time()
        return [
            cr.descriptor
            for cr in self._cache.get(server_name, [])
            if now - cr.cached_at < self._ttl
        ]

    def invalidate(self, server_name: str | None = None) -> None:
        """使缓存失效。"""
        if server_name:
            self._cache.pop(server_name, None)
        else:
            self._cache.clear()
