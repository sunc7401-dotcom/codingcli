"""MCP @提及 展开器 —— 对应 ``com.paicli.mcp.mention.AtMentionExpander``。

将 @server:scheme://path 替换为实际的 MCP 资源内容。
"""

from __future__ import annotations

from suncli_py.mcp.mention_parser import parse_mentions


class AtMentionExpander:
    def __init__(self, mcp_manager) -> None:
        self._mcp_manager = mcp_manager

    async def expand(self, text: str) -> str:
        mentions = parse_mentions(text)
        if not mentions:
            return text
        result = text
        for mention in mentions:
            content = await self._fetch_content(mention)
            if content:
                result = result.replace(mention.raw, f"{mention.raw}\n```\n{content}\n```")
        return result

    async def _fetch_content(self, mention) -> str | None:
        try:
            server = self._mcp_manager.get_server(mention.server_name)
            if not server or not server.is_ready:
                return None
            client = self._mcp_manager._clients.get(mention.server_name)
            if not client:
                return None
            uri = f"{mention.scheme}://{mention.path}"
            result = await client.read_resource(uri)
            return "\n".join(c.get("text", "") for c in result.get("contents", []) if c.get("text"))
        except Exception:
            return None
