"""MCP 资源子包。"""

from paicli_py.mcp._resources_core import CachedResource, McpResourceCache
from paicli_py.mcp.mcp_resource_descriptor import McpResourceDescriptor
from paicli_py.mcp.resource_tool import McpResourceTool

__all__ = ["CachedResource", "McpResourceCache", "McpResourceDescriptor", "McpResourceTool"]
