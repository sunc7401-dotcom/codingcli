"""MCP 通知路由器。

对应 ``com.paicli.mcp.notifications.NotificationRouter``。

按通知方法名路由到对应的处理器,
在独立线程上处理以避免死锁。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from loguru import logger

NotificationHandler = Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]


class NotificationRouter:
    """将入站的 JSON-RPC 通知按方法名分发给注册的处理器。"""

    def __init__(self) -> None:
        self._handlers: dict[str, list[NotificationHandler]] = {}

    def register(self, method: str, handler: NotificationHandler) -> None:
        """注册一个通知处理器。"""
        if method not in self._handlers:
            self._handlers[method] = []
        self._handlers[method].append(handler)

    def unregister(self, method: str, handler: NotificationHandler) -> None:
        """取消注册。"""
        handlers = self._handlers.get(method, [])
        if handler in handlers:
            handlers.remove(handler)

    async def dispatch(self, method: str, params: dict[str, Any]) -> None:
        """分发通知到所有注册的处理器。

        在独立任务上并发执行，异常不中断其他处理器。
        """
        handlers = self._handlers.get(method, [])
        if not handlers:
            return

        async def _safe_call(handler: NotificationHandler) -> None:
            try:
                await handler(method, params)
            except Exception as e:
                logger.warning(f"通知处理异常 ({method}): {e}")

        tasks = [asyncio.create_task(_safe_call(h)) for h in handlers]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
