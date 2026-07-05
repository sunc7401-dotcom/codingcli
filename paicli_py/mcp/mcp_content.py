"""MCP 内容类型 —— 对应 com.paicli.mcp.protocol 包中的内容类型。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class McpContent:
    type: str = "text"
    text: str | None = None
    data: str | None = None
    mime_type: str | None = None
    uri: str | None = None


@dataclass
class McpCallToolResult:
    content: list[McpContent] = field(default_factory=list)
    is_error: bool = False

    def text_content(self) -> str:
        return "\n".join(c.text for c in self.content if c.text)
