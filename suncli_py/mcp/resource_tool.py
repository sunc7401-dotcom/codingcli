"""MCP 资源工具 —— 将 MCP 资源包装为工具。

对应 ``com.paicli.mcp.resources.McpResourceTool``。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from suncli_py.mcp.manager import McpServerManager


class McpResourceTool:
    """虚拟工具：list_resources / read_resource。"""

    @staticmethod
    async def list_resources(manager: McpServerManager) -> str:
        """列出所有 MCP 服务器的资源。"""
        servers = manager.list_servers()
        lines: list[str] = []
        for srv in servers:
            if not srv.is_ready:
                continue
            client = manager._clients.get(srv.name)
            if not client:
                continue
            try:
                resources = await client.list_resources()
                for r in resources:
                    lines.append(f"[{srv.name}] {r.get('name', '?')}: {r.get('uri', '?')}")
            except Exception:
                lines.append(f"[{srv.name}] (获取资源列表失败)")
        return "\n".join(lines) if lines else "(无 MCP 资源)"

    @staticmethod
    async def read_resource(manager: McpServerManager, server_name: str, uri: str) -> str:
        """读取指定 MCP 资源的内容。"""
        client = manager._clients.get(server_name)
        if not client:
            return f"服务器未连接: {server_name}"
        try:
            result = await client.read_resource(uri)
            contents = result.get("contents", [])
            return "\n".join(c.get("text", "") for c in contents if c.get("text"))
        except Exception as e:
            return f"读取资源失败: {e}"
