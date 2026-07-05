"""MCP 传输层 —— Stdio + Streamable HTTP。

对应 ``com.paicli.mcp.transport`` 包。

- StdioTransport: 通过子进程 stdin/stdout 通信
- StreamableHttpTransport: 通过 HTTP POST + SSE 流式响应通信
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Coroutine

import httpx
from loguru import logger


# ────────────────────────────────────────────────
# StdioTransport
# ────────────────────────────────────────────────

class StdioTransport:
    """通过子进程标准输入/输出进行 JSON-RPC 通信。

    每行一个完整的 JSON 消息。
    stderr 保留在环形缓冲区中（最近 200 行）。
    """

    STDERR_RING_SIZE = 200

    def __init__(
        self,
        command: list[str],
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> None:
        self._command = command
        self._env = env
        self._cwd = cwd
        self._process: asyncio.subprocess.Process | None = None
        self._on_receive: Callable[[dict], Coroutine] | None = None
        self._stderr_lines: list[str] = []
        self._running = False

    @property
    def stderr_lines(self) -> list[str]:
        return list(self._stderr_lines)

    def set_on_receive(self, callback: Callable[[dict], Coroutine]) -> None:
        self._on_receive = callback

    async def start(self) -> None:
        """启动子进程并开始读取 stdout。"""
        self._process = await asyncio.create_subprocess_exec(
            *self._command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env,
            cwd=self._cwd,
        )
        self._running = True

        # 后台任务：读取 stdout 和 stderr
        asyncio.create_task(self._read_stdout())
        asyncio.create_task(self._read_stderr())

    async def send(self, message: dict) -> None:
        """向子进程 stdin 发送一条 JSON-RPC 消息。"""
        if not self._process or not self._process.stdin:
            raise RuntimeError("Transport 未启动")
        line = json.dumps(message, ensure_ascii=False) + "\n"
        self._process.stdin.write(line.encode("utf-8"))
        await self._process.stdin.drain()

    async def close(self) -> None:
        """关闭子进程。"""
        self._running = False
        if self._process:
            # 关闭 stdin，发送 EOF
            if self._process.stdin:
                self._process.stdin.close()

            # 等待进程退出（最多 5 秒）
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()

    # ── 内部 ────────────────────────────────────────────────

    async def _read_stdout(self) -> None:
        """读取子进程 stdout 的行并解析 JSON。"""
        if not self._process or not self._process.stdout:
            return

        while self._running:
            try:
                line = await self._process.stdout.readline()
                if not line:
                    break

                line_str = line.decode("utf-8").strip()
                if not line_str:
                    continue

                try:
                    message = json.loads(line_str)
                except json.JSONDecodeError:
                    logger.warning(f"MCP stdout 非 JSON 行: {line_str[:200]}")
                    continue

                if self._on_receive:
                    await self._on_receive(message)

            except Exception as e:
                if self._running:
                    logger.error(f"MCP stdout 读取异常: {e}")
                break

    async def _read_stderr(self) -> None:
        """读取 stderr 到环形缓冲区。"""
        if not self._process or not self._process.stderr:
            return

        while self._running:
            try:
                line = await self._process.stderr.readline()
                if not line:
                    break
                self._stderr_lines.append(line.decode("utf-8", errors="replace").rstrip())
                if len(self._stderr_lines) > self.STDERR_RING_SIZE:
                    self._stderr_lines.pop(0)
            except Exception:
                break


# ────────────────────────────────────────────────
# StreamableHttpTransport
# ────────────────────────────────────────────────

class StreamableHttpTransport:
    """通过 HTTP POST + SSE 流式响应进行 JSON-RPC 通信。

    支持会话管理（Mcp-Session-Id 标头）。
    """

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
        """通过 HTTP POST 发送 JSON-RPC 消息，解析 SSE 响应。"""
        if not self._client:
            raise RuntimeError("Transport 未启动")

        headers = {**self._headers, "Content-Type": "application/json"}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        try:
            async with self._client.stream("POST", self._url, json=message, headers=headers) as response:
                response.raise_for_status()

                # 处理 Session-Id 标头
                sid = response.headers.get("Mcp-Session-Id")
                if sid:
                    self._session_id = sid

                # 解析 SSE 内容
                async for line in response.aiter_lines():
                    trimmed = line.strip()
                    if not trimmed or not trimmed.startswith("data:"):
                        continue

                    payload = trimmed[len("data:"):].strip()
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
        """关闭 HTTP 会话（发送 DELETE 通知服务器）。"""
        if self._client:
            if self._session_id:
                try:
                    headers = {**self._headers}
                    headers["Mcp-Session-Id"] = self._session_id
                    await self._client.delete(self._url, headers=headers)
                except Exception:
                    pass
            await self._client.aclose()
            self._client = None
