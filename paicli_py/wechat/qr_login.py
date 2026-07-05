"""微信 QR 码登录 —— 对应 ``com.paicli.wechat.WechatQrLogin``。"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from paicli_py.wechat.login_result import WechatLoginResult

if TYPE_CHECKING:
    from paicli_py.wechat.client import IlinkClient


class WechatQrLogin:
    """微信 QR 码登录流程。"""

    POLL_INTERVAL = 2  # 秒
    MAX_POLL_TIME = 120  # 秒

    def __init__(self, client: IlinkClient) -> None:
        self._client = client

    async def login(self) -> WechatLoginResult:
        """完整 QR 码登录流程。

        1. 发起 QR 登录 → 获取 qr_data
        2. 终端渲染 QR 码
        3. 轮询等待用户扫码确认（最长 120s）
        """
        # 1. 发起
        try:
            qr_resp = await self._client.start_qr_login()
            qr_id = qr_resp.get("qrId", qr_resp.get("id", ""))
            qr_data = qr_resp.get("qrData", qr_resp.get("data", ""))
        except Exception as e:
            return WechatLoginResult(success=False, error=f"发起登录失败: {e}")

        if not qr_id:
            return WechatLoginResult(success=False, error="获取 QR ID 失败")

        # 2. 显示 QR 码
        self._render_qr(qr_data)

        # 3. 轮询
        import asyncio
        elapsed = 0
        while elapsed < self.MAX_POLL_TIME:
            result = await self._client.poll_qr_status(qr_id)
            if result.success:
                print("\n✅ 微信登录成功！")
                return result
            if "expired" in (result.error or "").lower():
                return result
            await asyncio.sleep(self.POLL_INTERVAL)
            elapsed += self.POLL_INTERVAL

        return WechatLoginResult(success=False, error="登录超时")

    @staticmethod
    def _render_qr(qr_data: str) -> None:
        """在终端渲染 QR 码。"""
        if not qr_data:
            print("⚠️ 无法获取 QR 码数据，请在微信中确认登录")
            return

        try:
            import qrcode
            qr = qrcode.QRCode()
            qr.add_data(qr_data)
            qr.print_ascii(out=sys.stderr)
        except ImportError:
            print(f"请扫描以下 QR 链接:\n{qr_data}", file=sys.stderr)
