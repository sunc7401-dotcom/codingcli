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


@dataclass(frozen=True)
class ParsedCommand:
    type: CommandType
    payload: str | None = None

    @classmethod
    def none(cls) -> ParsedCommand:
        return cls(CommandType.NONE)


def parse(input_str: str | None) -> ParsedCommand:
    if input_str is None:
        return ParsedCommand.none()
    t = input_str.strip()
    if not t:
        return ParsedCommand.none()
    tl = t.lower()

    if tl in ("/exit", "/quit", "exit", "quit"): return ParsedCommand(CommandType.EXIT)
    if tl in ("/cancel", "cancel"): return ParsedCommand(CommandType.CANCEL)
    if tl in ("/clear", "clear"): return ParsedCommand(CommandType.CLEAR)
    if tl == "/compact": return ParsedCommand(CommandType.COMPACT)
    if tl == "/history clear": return ParsedCommand(CommandType.HISTORY_CLEAR)
    if tl == "/init": return ParsedCommand(CommandType.INIT_PROJECT_MEMORY)
    if tl.startswith("/init "): return ParsedCommand(CommandType.INIT_PROJECT_MEMORY, t[6:].strip())
    if tl == "/model": return ParsedCommand(CommandType.SWITCH_MODEL)
    if tl.startswith("/model "): return ParsedCommand(CommandType.SWITCH_MODEL, t[7:].strip())
    if tl == "/plan": return ParsedCommand(CommandType.SWITCH_PLAN)
    if tl.startswith("/plan "): return ParsedCommand(CommandType.SWITCH_PLAN, t[6:].strip())
    if tl == "/team": return ParsedCommand(CommandType.SWITCH_TEAM)
    if tl.startswith("/team "): return ParsedCommand(CommandType.SWITCH_TEAM, t[6:].strip())
    if tl == "/hitl on": return ParsedCommand(CommandType.SWITCH_HITL, "on")
    if tl == "/hitl off": return ParsedCommand(CommandType.SWITCH_HITL, "off")
    if tl == "/hitl": return ParsedCommand(CommandType.SWITCH_HITL)
    if tl in ("/memory", "/mem"): return ParsedCommand(CommandType.MEMORY_STATUS)
    if tl in ("/memory clear", "/mem clear"): return ParsedCommand(CommandType.MEMORY_CLEAR)
    if tl in ("/memory list", "/mem list"): return ParsedCommand(CommandType.MEMORY_LIST)
    if tl.startswith("/memory delete ") or tl.startswith("/mem delete "):
        n = 15 if tl.startswith("/memory delete ") else 12
        return ParsedCommand(CommandType.MEMORY_DELETE, t[n:].strip())
    if tl.startswith("/memory search ") or tl.startswith("/mem search "):
        n = 15 if tl.startswith("/memory search ") else 12
        return ParsedCommand(CommandType.MEMORY_SEARCH, t[n:].strip())
    if tl == "/save": return ParsedCommand(CommandType.MEMORY_SAVE)
    if tl.startswith("/save "): return ParsedCommand(CommandType.MEMORY_SAVE, t[6:].strip())
    if tl == "/index": return ParsedCommand(CommandType.INDEX_CODE)
    if tl.startswith("/index "): return ParsedCommand(CommandType.INDEX_CODE, t[7:].strip())
    if tl == "/search": return ParsedCommand(CommandType.SEARCH_CODE)
    if tl.startswith("/search "): return ParsedCommand(CommandType.SEARCH_CODE, t[8:].strip())
    if tl == "/graph": return ParsedCommand(CommandType.GRAPH_QUERY)
    if tl.startswith("/graph "): return ParsedCommand(CommandType.GRAPH_QUERY, t[7:].strip())
    if tl in ("/context", "/ctx"): return ParsedCommand(CommandType.CONTEXT_STATUS)
    if tl == "/policy": return ParsedCommand(CommandType.POLICY_STATUS)
    if tl == "/config": return ParsedCommand(CommandType.CONFIG)
    if tl.startswith("/config "): return ParsedCommand(CommandType.CONFIG, t[8:].strip())
    if tl == "/audit": return ParsedCommand(CommandType.AUDIT_TAIL)
    if tl.startswith("/audit "): return ParsedCommand(CommandType.AUDIT_TAIL, t[7:].strip())
    if tl == "/snapshot": return ParsedCommand(CommandType.SNAPSHOT, "list")
    if tl.startswith("/snapshot "): return ParsedCommand(CommandType.SNAPSHOT, t[10:].strip())
    if tl == "/restore": return ParsedCommand(CommandType.RESTORE_SNAPSHOT)
    if tl.startswith("/restore "): return ParsedCommand(CommandType.RESTORE_SNAPSHOT, t[9:].strip())
    if tl == "/browser": return ParsedCommand(CommandType.BROWSER, "status")
    if tl.startswith("/browser "): return ParsedCommand(CommandType.BROWSER, t[9:].strip())
    if tl == "/wechat": return ParsedCommand(CommandType.WECHAT, "start")
    if tl.startswith("/wechat "): return ParsedCommand(CommandType.WECHAT, t[8:].strip())
    if tl == "/task": return ParsedCommand(CommandType.TASK, "list")
    if tl.startswith("/task "): return ParsedCommand(CommandType.TASK, t[6:].strip())
    if tl in ("/skill", "/skill list"): return ParsedCommand(CommandType.SKILL_LIST)
    if tl == "/skill reload": return ParsedCommand(CommandType.SKILL_RELOAD)
    if tl.startswith("/skill show "): return ParsedCommand(CommandType.SKILL_SHOW, t[12:].strip())
    if tl.startswith("/skill on "): return ParsedCommand(CommandType.SKILL_ON, t[10:].strip())
    if tl.startswith("/skill off "): return ParsedCommand(CommandType.SKILL_OFF, t[11:].strip())
    if tl == "/export": return ParsedCommand(CommandType.EXPORT)
    if tl == "/mcp": return ParsedCommand(CommandType.MCP_LIST)
    if tl.startswith("/mcp resources "): return ParsedCommand(CommandType.MCP_RESOURCES, t[15:].strip())
    if tl.startswith("/mcp prompts "): return ParsedCommand(CommandType.MCP_PROMPTS, t[13:].strip())
    if tl.startswith("/mcp restart "): return ParsedCommand(CommandType.MCP_RESTART, t[13:].strip())
    if tl.startswith("/mcp logs "): return ParsedCommand(CommandType.MCP_LOGS, t[10:].strip())
    if tl.startswith("/mcp disable "): return ParsedCommand(CommandType.MCP_DISABLE, t[13:].strip())
    if tl.startswith("/mcp enable "): return ParsedCommand(CommandType.MCP_ENABLE, t[12:].strip())
    if tl.startswith("/"):
        return ParsedCommand(CommandType.UNKNOWN_COMMAND, t)
    return ParsedCommand.none()
