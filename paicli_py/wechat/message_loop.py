"""微信消息循环 —— 对应 ``com.paicli.wechat.WechatMessageLoop``。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

from paicli_py.wechat.message import WechatMessage

if TYPE_CHECKING:
    from paicli_py.wechat.client import IlinkClient


class WechatMessageLoop:
    """微信消息长轮询循环。

    35s 超时长轮询 → 解析消息 → 去重 → 旁路命令处理或排队交给 Agent。
    """

    def __init__(self, client: IlinkClient) -> None:
        self._client = client
        self._running = False
        self._seen_message_ids: set[str] = set()
        self._message_queue: asyncio.Queue[WechatMessage] = asyncio.Queue()

    @property
    def message_queue(self) -> asyncio.Queue[WechatMessage]:
        return self._message_queue

    async def run(self) -> None:
        """启动消息循环。"""
        self._running = True
        sync_buf = ""

        while self._running:
            try:
                updates = await self._client.get_updates(sync_buf=sync_buf)
                for update in updates:
                    if update.message and update.message.message_id not in self._seen_message_ids:
                        self._seen_message_ids.add(update.message.message_id)
                        await self._message_queue.put(update.message)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.warning(f"微信消息轮询异常: {e}")
                await asyncio.sleep(5)

    def stop(self) -> None:
        self._running = False
