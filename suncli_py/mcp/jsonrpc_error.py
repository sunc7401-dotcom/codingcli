"""JSON-RPC 错误 —— 对应 com.paicli.mcp.jsonrpc 包中的错误类型。"""


class JsonRpcError(Exception):
    def __init__(self, code: int, message: str, data: object = None) -> None:
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"JSON-RPC Error {code}: {message}")
