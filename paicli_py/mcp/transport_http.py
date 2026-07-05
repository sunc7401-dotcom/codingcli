"""MCP Streamable HTTP 传输 —— 对应 com.paicli.mcp.transport.StreamableHttpTransport。"""

from __future__ import annotations

import json
from typing import Callable, Coroutine

import httpx
from loguru import logger


class StreamableHttpTransport:
    def __init__(self, url: str, headers: dict[str, str] | None = None) -> None:
        self._url = url
        self._headers = headers or {}
        self._session_id: str | None = None
        self._on_receive: Callable[[dict], Coroutine] | None = None
        self._client: httpx.AsyncClient | None = None

    def set_on_receive(self, callback: Callable[[dict], Coroutine]) -> None:
        self._on_receive = callback

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=60)

    async def send(self, message: dict) -> None:
        if not self._client:
            raise RuntimeError("Transport 未启动")
        headers = {**self._headers, "Content-Type": "application/json"}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        try:
            async with self._client.stream("POST", self._url, json=message, headers=headers) as resp:
                resp.raise_for_status()
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self._session_id = sid
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[len("data:"):].strip()
                    if not payload:
                        continue
                    try:
                        msg = json.loads(payload)
                        if self._on_receive:
                            await self._on_receive(msg)
                    except json.JSONDecodeError:
                        continue
        except httpx.HTTPError as e:
            logger.error(f"MCP HTTP 传输错误: {e}")
            raise

    async def close(self) -> None:
        if self._client:
            if self._session_id:
                try:
                    headers = {**self._headers, "Mcp-Session-Id": self._session_id}
                    await self._client.delete(self._url, headers=headers)
                except Exception:
                    pass
            await self._client.aclose()
            self._client = None
