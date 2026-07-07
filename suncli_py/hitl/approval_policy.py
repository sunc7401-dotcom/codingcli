"""审批策略 —— 对应 ``com.paicli.hitl.ApprovalPolicy``。"""

from __future__ import annotations


class ApprovalPolicy:
    """静态工具类——判断哪些工具需要审批、危险级别和风险描述。"""

    DANGEROUS_TOOLS: set[str] = {"write_file", "execute_command", "create_project", "revert_turn"}

    @classmethod
    def requires_approval(cls, tool_name: str) -> bool:
        """判断工具是否需要审批。内置工具检查 DANGEROUS_TOOLS，MCP 工具（mcp__前缀）一律需要审批。"""
        if tool_name.startswith("mcp__"):
            return True
        return tool_name in cls.DANGEROUS_TOOLS

    @classmethod
    def get_danger_level(cls, tool_name: str) -> str:
        """获取危险级别（带 emoji）。"""
        if tool_name == "execute_command" or tool_name == "revert_turn":
            return "🔴 高危"
        if tool_name == "write_file" or tool_name == "create_project":
            return "🟡 中危"
        if tool_name.startswith("mcp__"):
            return "🟡 MCP 外部工具"
        return "🟢 安全"

    @classmethod
    def get_risk_description(cls, tool_name: str) -> str:
        """获取风险描述。"""
        descriptions = {
            "write_file": "将修改或创建文件",
            "execute_command": "将执行 Shell 命令",
            "create_project": "将创建新项目",
            "revert_turn": "将回滚到上一轮快照",
        }
        if tool_name.startswith("mcp__"):
            return f"将调用外部 MCP 工具: {tool_name}"
        return descriptions.get(tool_name, f"将执行工具: {tool_name}")

    @classmethod
    def get_dangerous_tools(cls) -> set[str]:
        return cls.DANGEROUS_TOOLS.copy()

    @staticmethod
    def is_mcp_tool(tool_name: str) -> bool:
        return tool_name.startswith("mcp__")

    @staticmethod
    def mcp_server_name(tool_name: str) -> str | None:
        """提取 MCP 服务器名。"""
        if not tool_name.startswith("mcp__"):
            return None
        parts = tool_name.split("__")
        return parts[1] if len(parts) >= 2 else None
