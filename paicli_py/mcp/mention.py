"""MCP 资源 @提及 解析与展开。

对应 ``com.paicli.mcp.mention`` 包。

支持格式: ``@serverName:scheme://path``
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 匹配 @server:protocol://path 格式
_MENTION_RE = re.compile(r"@(\w[\w-]*):(\w+)://([^\s]+)")


@dataclass
class ParsedMention:
    """解析后的 @提及。"""
    server_name: str
    scheme: str
    path: str
    raw: str


def parse_mentions(text: str) -> list[ParsedMention]:
    """从文本中提取所有 @server:scheme://path 提及。"""
    mentions: list[ParsedMention] = []
    for match in _MENTION_RE.finditer(text):
        mentions.append(ParsedMention(
            server_name=match.group(1),
            scheme=match.group(2),
            path=match.group(3),
            raw=match.group(0),
        ))
    return mentions


class AtMentionExpander:
    """将 @提及 展开为内联资源内容。"""

    def __init__(self, mcp_manager) -> None:
        self._mcp_manager = mcp_manager

    async def expand(self, text: str) -> str:
        """展开文本中的所有 @提及。"""
        mentions = parse_mentions(text)
        if not mentions:
            return text

        result = text
        for mention in mentions:
            content = await self._fetch_content(mention)
            if content:
                replacement = f"{mention.raw}\n```\n{content}\n```"
                result = result.replace(mention.raw, replacement)

        return result

    async def _fetch_content(self, mention: ParsedMention) -> str | None:
        """获取 MCP 资源内容。"""
        try:
            server = self._mcp_manager.get_server(mention.server_name)
            if not server or not server.is_ready:
                return None

            client = self._mcp_manager._clients.get(mention.server_name)
            if not client:
                return None

            uri = f"{mention.scheme}://{mention.path}"
            result = await client.read_resource(uri)
            contents = result.get("contents", [])
            return "\n".join(c.get("text", "") for c in contents if c.get("text"))
        except Exception:
            return None
