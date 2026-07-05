"""浏览器连接性检测 —— 对应 ``com.paicli.browser.BrowserConnectivityCheck``。"""

from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass
class ProbeResult:
    ok: bool
    browser_url: str = ""
    message: str = ""

    @classmethod
    def ok_result(cls, browser_url: str) -> ProbeResult:
        return cls(ok=True, browser_url=browser_url)

    @classmethod
    def failed(cls, message: str) -> ProbeResult:
        return cls(ok=False, message=message)


class BrowserConnectivityCheck:
    """探测 Chrome DevTools 端口是否可用。"""

    def __init__(self) -> None:
        self._client = httpx.Client(timeout=2.0)

    def probe(self, port: int) -> ProbeResult:
        """检测指定端口上的 Chrome DevTools 是否可用。"""
        if port < 1024 or port > 65535:
            return ProbeResult.failed(f"端口号超出范围: {port}")

        url = f"http://127.0.0.1:{port}/json/version"
        try:
            resp = self._client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                browser = data.get("Browser", "未知")
                return ProbeResult.ok_result(f"http://127.0.0.1:{port} ({browser})")
            return ProbeResult.failed(f"HTTP {resp.status_code}")
        except Exception as e:
            return ProbeResult.failed(str(e))
