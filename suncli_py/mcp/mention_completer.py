"""MCP @提及 Tab 补全器。

对应 ``com.paicli.mcp.mention`` 包中的补全逻辑。
"""

from __future__ import annotations


class AtMentionCompleter:
    """为 @server: 开头的输入提供 Tab 补全。"""

    def __init__(self, mcp_manager) -> None:
        self._mcp_manager = mcp_manager

    def complete(self, prefix: str) -> list[str]:
        if not prefix.startswith("@"):
            return []
        # @server: → 列出该服务器的资源
        parts = prefix[1:].split(":", 1)
        if len(parts) == 1:
            # 补全服务器名
            servers = self._mcp_manager.list_servers()
            return [f"@{s.name}:" for s in servers if s.name.startswith(parts[0])]
        return []
