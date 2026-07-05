"""MCP Schema 清理器 —— 对应 ``com.paicli.mcp.protocol.McpSchemaSanitizer``。"""

from __future__ import annotations

_SKIP_KEYS = {"$ref", "$schema", "anyOf", "oneOf", "allOf", "not"}


def sanitize_schema(schema: dict) -> dict:
    """清理 JSON Schema 中 LLM 不支持的字段。"""
    if not isinstance(schema, dict):
        return schema
    result: dict = {}
    for k, v in schema.items():
        if k in _SKIP_KEYS:
            continue
        if isinstance(v, dict):
            result[k] = sanitize_schema(v)
        elif isinstance(v, list):
            result[k] = [sanitize_schema(i) if isinstance(i, dict) else i for i in v]
        else:
            result[k] = v
    return result
