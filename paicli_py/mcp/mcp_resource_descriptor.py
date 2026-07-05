"""MCP 资源描述符 —— 对应 com.paicli.mcp.resources 包中的资源类型。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class McpResourceDescriptor:
    uri: str = ""
    name: str = ""
    description: str = ""
    mime_type: str | None = None
    server_name: str = ""
