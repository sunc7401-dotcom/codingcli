"""MCP 初始化结果 —— 对应 com.paicli.mcp.protocol 包中的 initialize 类型。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class McpInitializeResult:
    protocol_version: str = "2025-03-26"
    server_info: dict = field(default_factory=dict)
    capabilities: dict = field(default_factory=dict)
