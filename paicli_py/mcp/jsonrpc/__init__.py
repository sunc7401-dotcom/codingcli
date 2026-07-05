"""MCP JSON-RPC 子包。"""

from paicli_py.mcp.jsonrpc import JsonRpcClient
from paicli_py.mcp.jsonrpc_error import JsonRpcError as JsonRpcException

__all__ = ["JsonRpcClient", "JsonRpcException"]
