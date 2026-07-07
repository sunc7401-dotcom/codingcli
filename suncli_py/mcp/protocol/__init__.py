"""MCP 协议类型子包。"""

from suncli_py.mcp.mcp_call_tool import McpCallToolRequest
from suncli_py.mcp.mcp_capabilities import McpCapabilities
from suncli_py.mcp.mcp_content import McpCallToolResult, McpContent
from suncli_py.mcp.mcp_initialize import McpInitializeResult
from suncli_py.mcp.mcp_initialize_request import McpInitializeRequest
from suncli_py.mcp.mcp_resource_descriptor import McpResourceDescriptor
from suncli_py.mcp.mcp_tool_descriptor import McpToolDescriptor
from suncli_py.mcp.schema_sanitizer import sanitize_schema as McpSchemaSanitizer

__all__ = [
    "McpCallToolRequest", "McpCallToolResult", "McpContent",
    "McpCapabilities", "McpInitializeRequest", "McpInitializeResult",
    "McpResourceDescriptor", "McpSchemaSanitizer", "McpToolDescriptor",
]
