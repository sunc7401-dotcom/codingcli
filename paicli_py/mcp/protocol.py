"""MCP 协议类型定义。

对应 ``com.paicli.mcp.protocol`` 包。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class McpToolDescriptor:
    """MCP 工具描述符。"""
    server_name: str
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)

    @property
    def namespaced_name(self) -> str:
        """命名空间格式: mcp__<server>__<tool>"""
        return f"mcp__{self.server_name}__{self.name}"


@dataclass
class McpContent:
    """MCP 内容项（文本/图片/资源）。"""
    type: str  # "text" | "image" | "resource"
    text: str | None = None
    data: str | None = None  # base64 for image
    mime_type: str | None = None
    uri: str | None = None  # for resource


@dataclass
class McpCallToolResult:
    """MCP 工具调用结果。"""
    content: list[McpContent] = field(default_factory=list)
    is_error: bool = False

    def text_content(self) -> str:
        """提取所有文本内容拼接。"""
        return "\n".join(c.text for c in self.content if c.text)


@dataclass
class McpCapabilities:
    """MCP 服务器能力声明。"""
    tools: dict[str, Any] | None = None
    resources: dict[str, Any] | None = None
    prompts: dict[str, Any] | None = None


@dataclass
class McpInitializeResult:
    """MCP initialize 响应。"""
    protocol_version: str
    server_info: dict[str, Any] = field(default_factory=dict)
    capabilities: McpCapabilities = field(default_factory=McpCapabilities)


@dataclass
class McpResourceDescriptor:
    """MCP 资源描述符。"""
    uri: str
    name: str
    description: str = ""
    mime_type: str | None = None
    server_name: str = ""


class McpSchemaSanitizer:
    """清理 JSON Schema 中的不可序列化字段。

    移除 $ref, $schema, anyOf/oneOf 等 LLM 不支持的字段。
    """

    @staticmethod
    def sanitize(schema: dict[str, Any]) -> dict[str, Any]:
        """返回清理后的 schema 副本。"""
        if not isinstance(schema, dict):
            return schema

        cleaned: dict[str, Any] = {}
        skip_keys = {"$ref", "$schema", "anyOf", "oneOf", "allOf", "not"}
        for key, value in schema.items():
            if key in skip_keys:
                continue
            if isinstance(value, dict):
                cleaned[key] = McpSchemaSanitizer.sanitize(value)
            elif isinstance(value, list):
                cleaned[key] = [
                    McpSchemaSanitizer.sanitize(v) if isinstance(v, dict) else v
                    for v in value
                ]
            else:
                cleaned[key] = value
        return cleaned
