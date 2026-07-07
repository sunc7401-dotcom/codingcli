"""微信消息发送器 —— 对应 com.paicli.wechat.WechatMessageSender。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from suncli_py.wechat.client import IlinkClient


class WechatMessageSender:
    def __init__(self, client: IlinkClient) -> None:
        self._client = client

    async def send(self, to_user_id: str, text: str) -> None:
        chunks = self._split_text(text)
        for chunk in chunks:
            await self._client.send_text(to_user_id, chunk)

    async def send_typing(self, to_user_id: str) -> None:
        await self._client.send_typing(to_user_id)

    @staticmethod
    def _split_text(text: str, max_len: int = 3800) -> list[str]:
        if len(text) <= max_len:
            return [text]
        return [text[i:i + max_len] for i in range(0, len(text), max_len)]
