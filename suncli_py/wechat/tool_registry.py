"""微信工具注册表 —— 对应 ``com.paicli.wechat.WechatToolRegistry``。"""

from suncli_py.tool.registry import ToolRegistry


class WechatToolRegistry(ToolRegistry):
    """针对微信场景定制的工具注册表。

    移除了不适用于微信场景的工具（如 browser_*），
    添加了微信特有的消息发送工具。
    """

    def __init__(self) -> None:
        super().__init__()
        self._register_wechat_tools()

    def _register_wechat_tools(self) -> None:
        self.register(
            name="send_wechat_message",
            description="通过微信向用户发送消息。",
            parameters={
                "type": "object",
                "properties": {"content": {"type": "string", "description": "消息内容"}},
                "required": ["content"],
            },
            executor=self._send_wechat_message,
        )

    async def _send_wechat_message(self, params: dict) -> str:
        return f"[微信消息] {params.get('content', '')}"
