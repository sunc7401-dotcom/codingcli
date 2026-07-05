"""JSON-RPC 2.0 客户端。

对应 ``com.paicli.mcp.jsonrpc.JsonRpcClient``。

基于 asyncio.Future 的请求/响应匹配，
支持请求超时和通知分发。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Callable, Coroutine

from loguru import logger


class JsonRpcError(Exception):
    """JSON-RPC 协议错误。"""
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"JSON-RPC Error {code}: {message}")


class JsonRpcClient:
    """JSON-RPC 2.0 客户端。

    用法::

        transport = StdioTransport(command=["python", "server.py"])
        rpc = JsonRpcClient(transport)
        await rpc.start()

        result = await rpc.request("tools/list", {})
        rpc.send_notification("notifications/initialized", {})
    """

    DEFAULT_TIMEOUT = 30  # 秒

    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future[dict]] = {}
        self._notification_listeners: list[Callable[[str, dict], Coroutine]] = []
        self._response_queue: asyncio.Queue[dict] = asyncio.Queue()
        self._running = False
        self._task: asyncio.Task | None = None

    # ── 请求 ────────────────────────────────────────────────

    async def request(self, method: str, params: dict | None = None, timeout: float = DEFAULT_TIMEOUT) -> dict:
        """发送 JSON-RPC 请求，等待响应。"""
        request_id = uuid.uuid4().hex[:12]
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }

        future: asyncio.Future[dict] = asyncio.get_event_loop().create_future()
        self._pending[request_id] = future

        await self._send(message)

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            raise JsonRpcError(-32000, f"请求超时 ({timeout}s): {method}")

    def send_notification(self, method: str, params: dict | None = None) -> None:
        """发送 JSON-RPC 通知（无响应）。"""
        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }
        asyncio.create_task(self._send(message))

    # ── 传输绑定 ────────────────────────────────────────────

    def set_send_handler(self, handler: Callable[[dict], Coroutine]) -> None:
        """绑定发送处理函数（由 transport 调用）。"""
        self._send = handler

    async def handle_message(self, raw: dict) -> None:
        """处理一条接收到的 JSON-RPC 消息。

        由 transport 在收到消息时调用。
        """
        if "id" in raw and "method" not in raw:
            # 响应
            req_id = str(raw["id"])
            future = self._pending.pop(req_id, None)
            if future and not future.done():
                if "error" in raw:
                    err = raw["error"]
                    future.set_exception(JsonRpcError(
                        code=err.get("code", -1),
                        message=err.get("message", "Unknown error"),
                        data=err.get("data"),
                    ))
                else:
                    future.set_result(raw.get("result", {}))
        elif "method" in raw:
            # 通知或请求（无 id）
            await self._dispatch_notification(raw["method"], raw.get("params", {}))

    # ── 通知监听 ────────────────────────────────────────────

    def on_notification(self, callback: Callable[[str, dict], Coroutine]) -> None:
        """注册通知监听器。"""
        self._notification_listeners.append(callback)

    async def _dispatch_notification(self, method: str, params: dict) -> None:
        for listener in self._notification_listeners:
            try:
                await listener(method, params)
            except Exception as e:
                logger.warning(f"通知处理异常 ({method}): {e}")
