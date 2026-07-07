"""MCP 服务器状态枚举 —— 对应 ``com.paicli.mcp.McpServerStatus``。"""

from enum import Enum


class McpServerStatus(str, Enum):
    DISABLED = "DISABLED"
    STARTING = "STARTING"
    READY = "READY"
    ERROR = "ERROR"
