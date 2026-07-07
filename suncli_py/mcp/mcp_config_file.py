"""MCP 配置文件模型 —— 对应 ``com.paicli.mcp.config.McpConfigFile``。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class McpServerConfig:
    """单个 MCP 服务器配置。"""
    name: str = ""
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    disabled: bool = False

    @property
    def is_stdio(self) -> bool:
        return self.command is not None

    @property
    def is_http(self) -> bool:
        return self.url is not None


@dataclass
class McpConfigFile:
    """MCP 配置文件的顶层结构。"""
    mcp_servers: dict[str, McpServerConfig] = field(default_factory=dict)
