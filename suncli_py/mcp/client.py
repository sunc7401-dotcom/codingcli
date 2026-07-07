"""MCP 客户端 —— 封装 JSON-RPC + 传输层。

对应 ``com.paicli.mcp.McpClient``。
"""

from __future__ import annotations

from typing import Any

from suncli_py.mcp.jsonrpc import JsonRpcClient
from suncli_py.mcp.protocol import (
    McpCallToolResult,
    McpContent,
    McpInitializeResult,
    McpToolDescriptor,
)
from suncli_py.mcp.transport import StdioTransport, StreamableHttpTransport


class McpClient:
    """MCP 客户端 —— 管理与单个 MCP 服务器的通信。

    使用流程::

        transport = StdioTransport(command=["python", "server.py"])
        client = McpClient(transport)
        await client.initialize()
        tools = await client.list_tools()
        result = await client.call_tool("my_tool", {"arg": "value"})
        await client.close()
    """

    PROTOCOL_VERSION = "2025-03-26"

    def __init__(self, transport: StdioTransport | StreamableHttpTransport) -> None:
        self._transport = transport
        self._rpc = JsonRpcClient()
        self._server_info: dict[str, Any] = {}
        self._capabilities: dict[str, Any] = {}

        # 绑定传输到 RPC
        self._transport.set_on_receive(self._rpc.handle_message)
        self._rpc.set_send_handler(self._transport.send)

    async def initialize(self) -> McpInitializeResult:
        """发送 initialize 请求，完成握手。"""
        await self._transport.start()

        result = await self._rpc.request(
            "initialize",
            {
                "protocolVersion": self.PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "PaiCLI-Py", "version": "16.1.0"},
            },
        )

        self._server_info = result.get("serverInfo", {})
        self._capabilities = result.get("capabilities", {})

        # 发送 initialized 通知
        self._rpc.send_notification("notifications/initialized", {})

        return McpInitializeResult(
            protocol_version=result.get("protocolVersion", self.PROTOCOL_VERSION),
            server_info=self._server_info,
            capabilities=self._capabilities,
        )

    async def list_tools(self) -> list[McpToolDescriptor]:
        """获取服务器提供的工具列表。"""
        result = await self._rpc.request("tools/list", {})
        tools: list[McpToolDescriptor] = []
        for item in result.get("tools", []):
            tools.append(McpToolDescriptor(
                server_name=self._server_info.get("name", "unknown"),
                name=item.get("name", ""),
                description=item.get("description", ""),
                input_schema=item.get("inputSchema", {}),
            ))
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> McpCallToolResult:
        """调用一个 MCP 工具。"""
        result = await self._rpc.request("tools/call", {
            "name": name,
            "arguments": arguments,
        })

        content: list[McpContent] = []
        for item in result.get("content", []):
            content.append(McpContent(
                type=item.get("type", "text"),
                text=item.get("text"),
                data=item.get("data"),
                mime_type=item.get("mimeType"),
            ))

        return McpCallToolResult(
            content=content,
            is_error=result.get("isError", False),
        )

    async def list_resources(self) -> list[dict]:
        """获取资源列表。"""
        result = await self._rpc.request("resources/list", {})
        return result.get("resources", [])

    async def read_resource(self, uri: str) -> dict:
        """读取指定资源的内容。"""
        return await self._rpc.request("resources/read", {"uri": uri})

    async def list_prompts(self) -> list[dict]:
        """获取提示词模板列表。"""
        result = await self._rpc.request("prompts/list", {})
        return result.get("prompts", [])

    async def close(self) -> None:
        """关闭传输。"""
        await self._transport.close()
