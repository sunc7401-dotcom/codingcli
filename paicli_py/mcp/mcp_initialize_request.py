"""MCP 初始化请求 —— 对应 com.paicli.mcp.protocol 包。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class McpInitializeRequest:
    protocol_version: str = "2025-03-26"
    capabilities: dict = field(default_factory=dict)
    client_info: dict = field(default_factory=dict)
