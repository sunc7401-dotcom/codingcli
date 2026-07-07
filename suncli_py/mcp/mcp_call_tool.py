"""MCP 工具调用请求/响应 —— 对应 com.paicli.mcp.protocol 包。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class McpCallToolRequest:
    name: str = ""
    arguments: dict = field(default_factory=dict)
