"""微信 iLink HTTP 客户端 —— 对应 ``com.paicli.wechat.IlinkClient``。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from suncli_py.wechat.login_result import WechatLoginResult
from suncli_py.wechat.message import WechatMessage


@dataclass
class WechatUpdate:
    update_id: str
    message: WechatMessage | None = None
    raw: dict[str, Any] | None = None


class IlinkClient:
    """微信 iLink API 客户端。

    功能：
    - QR 码登录
    - 长轮询消息拉取 (get_updates)
    - 发送文本消息
    - 发送正在输入状态
    """

    def __init__(self, base_url: str = "https://ilink.weixin.qq.com") -> None:
        self._base_url = base_url.rstrip("/")
        self._token: str = ""
        self._client = httpx.AsyncClient(timeout=60)

    @property
    def token(self) -> str:
        return self._token

    def set_token(self, token: str) -> None:
        self._token = token

    # ── QR 登录 ──────────────────────────────────────────

    async def start_qr_login(self) -> dict[str, Any]:
        """发起 QR 码登录，返回 qr_data。"""
        resp = await self._client.post(
            f"{self._base_url}/api/qr/login/start",
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()

    async def poll_qr_status(self, qr_id: str) -> WechatLoginResult:
        """轮询 QR 码扫描状态。"""
        resp = await self._client.get(
            f"{self._base_url}/api/qr/login/status",
            params={"qrId": qr_id},
        )
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status", "")
        if status == "confirmed":
            self._token = data.get("botToken", data.get("token", ""))
            return WechatLoginResult(
                success=True,
                token=self._token,
                account_id=data.get("accountId", ""),
            )
        elif status == "expired":
            return WechatLoginResult(success=False, error="QR 码已过期")
        return WechatLoginResult(success=False, error=f"等待扫描: {status}")

    # ── 消息 ──────────────────────────────────────────────

    async def get_updates(self, sync_buf: str = "", timeout: int = 35) -> list[WechatUpdate]:
        """长轮询拉取消息。"""
        body: dict[str, Any] = {"syncBuf": sync_buf} if sync_buf else {}
        resp = await self._client.post(
            f"{self._base_url}/api/message/updates",
            json=body,
            headers=self._auth_headers(),
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        updates: list[WechatUpdate] = []
        for item in data.get("updates", []):
            msg_data = item.get("message", {})
            msg = WechatMessage(
                message_id=msg_data.get("messageId", item.get("updateId", "")),
                from_user_id=msg_data.get("fromUserId", ""),
                context_token=msg_data.get("contextToken", ""),
                text=msg_data.get("text", msg_data.get("content", "")),
            )
            updates.append(WechatUpdate(update_id=item.get("updateId", ""), message=msg, raw=item))
        return updates

    async def send_text(self, to_user_id: str, text: str) -> None:
        """发送文本消息。"""
        body = {"toUserId": to_user_id, "text": text, "msgType": "text"}
        resp = await self._client.post(
            f"{self._base_url}/api/message/send",
            json=body,
            headers=self._auth_headers(),
        )
        resp.raise_for_status()

    async def send_typing(self, to_user_id: str) -> None:
        """发送正在输入状态。"""
        body = {"toUserId": to_user_id, "msgType": "typing"}
        resp = await self._client.post(
            f"{self._base_url}/api/message/send",
            json=body,
            headers=self._auth_headers(),
        )
        resp.raise_for_status()

    async def close(self) -> None:
        await self._client.aclose()

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
