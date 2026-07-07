"""微信登录流程封装 —— 对应 com.paicli.wechat 包。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from suncli_py.wechat.client import IlinkClient
    from suncli_py.wechat.login_result import WechatLoginResult


class WechatLogin:
    def __init__(self, client: IlinkClient) -> None:
        self._client = client

    async def login(self) -> WechatLoginResult:
        qr_resp = await self._client.start_qr_login()
        qr_id = qr_resp.get("qrId", qr_resp.get("id", ""))
        if not qr_id:
            from suncli_py.wechat.login_result import WechatLoginResult
            return WechatLoginResult(success=False, error="无法获取 QR ID")
        for _ in range(60):
            result = await self._client.poll_qr_status(qr_id)
            if result.success:
                return result
            await asyncio.sleep(2)
        from suncli_py.wechat.login_result import WechatLoginResult
        return WechatLoginResult(success=False, error="登录超时")
