"""MCP @提及 解析器 —— 对应 ``com.paicli.mcp.mention.AtMentionParser``。

解析用户输入中的 @server:scheme://path 格式。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_MENTION_RE = re.compile(r"@(\w[\w-]*):(\w+)://([^\s]+)")


@dataclass
class ParsedMention:
    server_name: str
    scheme: str
    path: str
    raw: str


def parse_mentions(text: str) -> list[ParsedMention]:
    mentions: list[ParsedMention] = []
    for m in _MENTION_RE.finditer(text):
        mentions.append(ParsedMention(server_name=m.group(1), scheme=m.group(2), path=m.group(3), raw=m.group(0)))
    return mentions
