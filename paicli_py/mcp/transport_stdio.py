"""MCP Stdio 传输 —— 对应 com.paicli.mcp.transport.StdioTransport。"""

from __future__ import annotations

import asyncio
import json
from typing import Callable, Coroutine

from loguru import logger


class StdioTransport:
    STDERR_RING_SIZE = 200

    def __init__(self, command: list[str], env: dict[str, str] | None = None, cwd: str | None = None) -> None:
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
        self._process = await asyncio.create_subprocess_exec(
            *self._command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=self._env, cwd=self._cwd,
        )
        self._running = True
        asyncio.create_task(self._read_stdout())
        asyncio.create_task(self._read_stderr())

    async def send(self, message: dict) -> None:
        if not self._process or not self._process.stdin:
            raise RuntimeError("Transport 未启动")
        line = json.dumps(message, ensure_ascii=False) + "\n"
        self._process.stdin.write(line.encode("utf-8"))
        await self._process.stdin.drain()

    async def close(self) -> None:
        self._running = False
        if self._process:
            if self._process.stdin:
                self._process.stdin.close()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()

    async def _read_stdout(self) -> None:
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
                msg = json.loads(line_str)
                if self._on_receive:
                    await self._on_receive(msg)
            except json.JSONDecodeError:
                logger.warning(f"MCP stdout 非 JSON: {line_str[:200]}" if 'line_str' in dir() else "MCP stdout 读取异常")
            except Exception as e:
                if self._running:
                    logger.error(f"MCP stdout 异常: {e}")
                break

    async def _read_stderr(self) -> None:
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
