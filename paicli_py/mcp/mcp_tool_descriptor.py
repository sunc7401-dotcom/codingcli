"""MCP 工具描述符 —— 对应 com.paicli.mcp.protocol.McpToolDescriptor。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class McpToolDescriptor:
    server_name: str = ""
    name: str = ""
    description: str = ""
    input_schema: dict = field(default_factory=dict)

    @property
    def namespaced_name(self) -> str:
        return f"mcp__{self.server_name}__{self.name}"
