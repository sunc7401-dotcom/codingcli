"""浏览器连接器 —— 管理 Chrome DevTools 连接。

对应 ``com.paicli.browser.BrowserConnector`` 和 ``BrowserConnectivityCheck``。
"""

from __future__ import annotations

import httpx


class BrowserConnector:
    """Chrome DevTools Protocol 连接器。

    提供连接状态查询、默认连接、断开连接功能。
    """

    def __init__(self, browser_url: str = "http://127.0.0.1:9222") -> None:
        self._browser_url = browser_url

    async def status(self) -> str:
        """获取当前连接状态。"""
        ok, msg = await self._probe()
        if ok:
            return f"✅ 已连接: {self._browser_url}\n{msg}"
        return f"❌ 未连接: {msg}"

    async def connect_default(self) -> str:
        """连接到默认 Chrome 实例。"""
        ok, msg = await self._probe()
        if ok:
            return f"已连接到: {self._browser_url}"
        return f"连接失败: {msg}"

    async def disconnect(self) -> str:
        """断开连接（无操作，Chrome CDP 不保持长连接）。"""
        return "已断开"

    async def _probe(self) -> tuple[bool, str]:
        """探测 Chrome DevTools 是否可用。"""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{self._browser_url}/json/version")
                if resp.status_code == 200:
                    data = resp.json()
                    browser = data.get("Browser", "未知")
                    return True, f"Chrome: {browser}"
                return False, f"HTTP {resp.status_code}"
        except Exception as e:
            return False, str(e)
