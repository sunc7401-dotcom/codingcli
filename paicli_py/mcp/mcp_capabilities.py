"""MCP 能力声明 —— 对应 com.paicli.mcp.protocol 包中的 capabilities 类型。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class McpCapabilities:
    tools: dict | None = None
    resources: dict | None = None
    prompts: dict | None = None
