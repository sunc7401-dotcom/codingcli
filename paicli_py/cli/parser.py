"""CLI 命令解析器。

对应 ``com.paicli.cli.CliCommandParser``。

将用户输入解析为 CommandType + payload。
命令全部以 / 开头（部分也支持不带 / 的别名）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class CommandType(Enum):
    """命令类型枚举（共 43 个，与 Java 版一致）。"""
    NONE = auto()
    UNKNOWN_COMMAND = auto()
    INIT_PROJECT_MEMORY = auto()
    CANCEL = auto()
    EXIT = auto()
    CLEAR = auto()
    COMPACT = auto()
    HISTORY_CLEAR = auto()
    SWITCH_MODEL = auto()
    SWITCH_PLAN = auto()
    SWITCH_TEAM = auto()
    SWITCH_HITL = auto()
    MEMORY_STATUS = auto()
    MEMORY_CLEAR = auto()
    MEMORY_LIST = auto()
    MEMORY_DELETE = auto()
    MEMORY_SEARCH = auto()
    MEMORY_SAVE = auto()
    INDEX_CODE = auto()
    SEARCH_CODE = auto()
    GRAPH_QUERY = auto()
    CONTEXT_STATUS = auto()
    POLICY_STATUS = auto()
    AUDIT_TAIL = auto()
    SNAPSHOT = auto()
    RESTORE_SNAPSHOT = auto()
    MCP_LIST = auto()
    MCP_RESTART = auto()
    MCP_LOGS = auto()
    MCP_DISABLE = auto()
    MCP_ENABLE = auto()
    MCP_RESOURCES = auto()
    MCP_PROMPTS = auto()
    BROWSER = auto()
    WECHAT = auto()
    TASK = auto()
    SKILL_LIST = auto()
    SKILL_SHOW = auto()
    SKILL_ON = auto()
    SKILL_OFF = auto()
    SKILL_RELOAD = auto()
    CONFIG = auto()
    EXPORT = auto()
