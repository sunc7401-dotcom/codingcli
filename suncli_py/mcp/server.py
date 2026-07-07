"""MCP 服务器状态模型。

对应 ``com.paicli.mcp.McpServer`` 和 ``McpServerStatus``。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

from suncli_py.mcp.protocol import McpToolDescriptor


class McpServerStatus(str, Enum):
    DISABLED = "DISABLED"
    STARTING = "STARTING"
    READY = "READY"
    ERROR = "ERROR"


@dataclass
class McpServer:
    """单个 MCP 服务器的运行时状态。"""

    name: str
    config: dict  # McpServerConfig
    status: McpServerStatus = McpServerStatus.DISABLED
    tools: list[McpToolDescriptor] = field(default_factory=list)
    error_message: str | None = None
    started_at: float | None = None

    @property
    def uptime_seconds(self) -> float:
        if self.started_at is None:
            return 0.0
        return time.time() - self.started_at

    @property
    def is_ready(self) -> bool:
        return self.status == McpServerStatus.READY
