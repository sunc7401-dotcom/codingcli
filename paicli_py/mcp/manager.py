"""MCP 服务器管理器 —— 门面类。

对应 ``com.paicli.mcp.McpServerManager``。

管理所有 MCP 服务器的生命周期：启动、重启、禁用、启用、
工具列表同步、资源缓存。
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from loguru import logger

from paicli_py.mcp.client import McpClient
from paicli_py.mcp.config import McpConfigLoader, McpServerConfig
from paicli_py.mcp.server import McpServer, McpServerStatus
from paicli_py.mcp.transport import StdioTransport, StreamableHttpTransport

if TYPE_CHECKING:
    from paicli_py.tool.registry import ToolRegistry


class McpServerManager:
    """MCP 服务器生命周期管理器。

    使用示例::

        manager = McpServerManager(tool_registry)
        await manager.start_all("/path/to/project")

        # 查询
        servers = manager.list_servers()
        logs = manager.get_logs("my-server")
    """

    def __init__(self, tool_registry: ToolRegistry | None = None) -> None:
        self._servers: dict[str, McpServer] = {}
        self._clients: dict[str, McpClient] = {}  # server_name → client
        self._tool_registry = tool_registry

    # ── 启动 / 停止 ────────────────────────────────────────

    async def start_all(self, project_dir: str | None = None) -> None:
        """加载配置并并行启动所有非禁用服务器。"""
        configs = McpConfigLoader.load(project_dir)

        # 并行启动（最多 4 个并发）
        semaphore = asyncio.Semaphore(4)

        async def _start_one(name: str, cfg: McpServerConfig) -> None:
            async with semaphore:
                await self._start_server(name, cfg)

        tasks = [
            _start_one(name, cfg)
            for name, cfg in configs.items()
            if not cfg.disabled
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _start_server(self, name: str, cfg: McpServerConfig) -> None:
        """启动单个 MCP 服务器。"""
        server = McpServer(name=name, config=cfg.__dict__ if hasattr(cfg, '__dict__') else cfg)
        server.status = McpServerStatus.STARTING
        server.started_at = time.time()
        self._servers[name] = server

        try:
            # 创建传输
            if cfg.is_stdio:
                command = [cfg.command] + (cfg.args if hasattr(cfg, 'args') else [])
                transport = StdioTransport(command=command, env=cfg.env if hasattr(cfg, 'env') else None)
            elif cfg.is_http:
                transport = StreamableHttpTransport(url=cfg.url, headers=cfg.headers if hasattr(cfg, 'headers') else None)
            else:
                server.status = McpServerStatus.ERROR
                server.error_message = "配置错误：需要 command 或 url"
                return

            # 初始化 MCP 客户端
            client = McpClient(transport)
            await client.initialize()

            # 获取工具列表
            tools = await client.list_tools()
            server.tools = tools
            server.status = McpServerStatus.READY
            self._clients[name] = client

            # 注册 MCP 工具到 ToolRegistry
            if self._tool_registry:
                self._register_mcp_tools(name, tools)

            logger.info(f"MCP 服务器 {name} 启动成功，{len(tools)} 个工具")

        except Exception as e:
            server.status = McpServerStatus.ERROR
            server.error_message = str(e)
            logger.error(f"MCP 服务器 {name} 启动失败: {e}")

    # ── 重启 / 控制 ────────────────────────────────────────

    async def restart(self, name: str) -> None:
        """重启指定服务器。"""
        await self._stop_server(name)
        # 重新加载配置
        configs = McpConfigLoader.load()
        cfg = configs.get(name)
        if cfg:
            await self._start_server(name, cfg)

    async def disable(self, name: str) -> None:
        """禁用并停止服务器。"""
        await self._stop_server(name)
        if name in self._servers:
            self._servers[name].status = McpServerStatus.DISABLED

    async def enable(self, name: str) -> None:
        """启用服务器（重新启动）。"""
        await self.restart(name)

    async def _stop_server(self, name: str) -> None:
        """停止单个服务器。"""
        # 移除工具注册
        if self._tool_registry and name in self._servers:
            server = self._servers[name]
            for tool in server.tools:
                self._tool_registry.unregister(tool.namespaced_name)

        # 关闭客户端
        client = self._clients.pop(name, None)
        if client:
            try:
                await client.close()
            except Exception as e:
                logger.warning(f"MCP 服务器 {name} 关闭异常: {e}")

    async def shutdown_all(self) -> None:
        """关闭所有服务器。"""
        for name in list(self._clients):
            await self._stop_server(name)

    # ── 查询 ────────────────────────────────────────────────

    def list_servers(self) -> list[McpServer]:
        return list(self._servers.values())

    def get_server(self, name: str) -> McpServer | None:
        return self._servers.get(name)

    def get_logs(self, name: str) -> list[str]:
        """获取服务器的 stderr 日志（仅 StdioTransport 有）。"""
        client = self._clients.get(name)
        if client and hasattr(client._transport, "stderr_lines"):
            return client._transport.stderr_lines
        return []

    # ── 内部 ────────────────────────────────────────────────

    def _register_mcp_tools(self, server_name: str, tools: list) -> None:
        """将 MCP 工具注册到 ToolRegistry。"""
        if not self._tool_registry:
            return

        for tool in tools:
            namespaced = tool.namespaced_name

            async def _executor(params: dict, _client=self._clients.get(server_name), _name=tool.name) -> str:
                if _client is None:
                    return f"MCP 服务器 {server_name} 未连接"
                result = await _client.call_tool(_name, params)
                return result.text_content()

            self._tool_registry.register(
                name=namespaced,
                description=f"[MCP:{server_name}] {tool.description}",
                parameters=tool.input_schema,
                executor=_executor,
                source="mcp",
            )
