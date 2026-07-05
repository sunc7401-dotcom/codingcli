"""MCP 工具列表请求/响应 —— 对应 com.paicli.mcp.protocol 包。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class McpListToolsResult:
    tools: list[dict] = field(default_factory=list)
