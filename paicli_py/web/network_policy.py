"""网络策略 —— URL/IP 访问控制 + 速率限制。

对应 ``com.paicli.web.NetworkPolicy``。
"""

from __future__ import annotations

import ipaddress
import re
import socket
import time
from urllib.parse import urlparse


class NetworkPolicy:
    """网络访问控制策略（实例化，非静态）。"""

    _BLOCKED_NETWORKS = [
        ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"), ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("169.254.0.0/16"), ipaddress.ip_network("0.0.0.0/8"),
        ipaddress.ip_network("::1/128"), ipaddress.ip_network("fc00::/7"),
        ipaddress.ip_network("fe80::/10"),
    ]

    _MAX_REQUESTS = 30
    _WINDOW_SECONDS = 60

    def __init__(self) -> None:
        self._request_times: list[float] = []

    def check_url(self, url: str) -> str | None:
        """检查 URL 是否允许访问。"""
        try:
            parsed = urlparse(url)
        except Exception:
            return f"URL 解析失败: {url}"

        if parsed.scheme not in ("http", "https"):
            return f"不支持的协议: {parsed.scheme}"

        hostname = parsed.hostname
        if not hostname:
            return "URL 缺少主机名"

        # 本地地址快速拒绝
        host_lower = hostname.lower()
        if host_lower in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
            return f"禁止访问本地地址: {hostname}"

        # IP 黑名单
        try:
            addr = ipaddress.ip_address(hostname)
            if addr.is_loopback:
                return f"禁止访问回环地址: {hostname}"
            for net in self._BLOCKED_NETWORKS:
                if addr in net:
                    return f"禁止访问内网地址: {hostname}"
        except ValueError:
            pass

        # DNS 解析检查
        try:
            resolved = socket.getaddrinfo(hostname, None)
            for _, _, _, _, sockaddr in resolved:
                ip_str = sockaddr[0]
                try:
                    addr = ipaddress.ip_address(ip_str)
                    if addr.is_loopback or addr.is_link_local or addr.is_private:
                        return f"DNS 解析到内网地址: {hostname} → {ip_str}"
                except ValueError:
                    pass
        except OSError:
            return f"无法解析主机: {hostname}"

        return None

    def acquire(self) -> str | None:
        """令牌桶速率限制。

        Returns:
            None 表示放行；非 None 字符串表示拒绝原因。
        """
        now = time.time()
        self._request_times[:] = [t for t in self._request_times if now - t < self._WINDOW_SECONDS]
        if len(self._request_times) >= self._MAX_REQUESTS:
            return f"速率限制: {self._MAX_REQUESTS} 次 / {self._WINDOW_SECONDS}s"
        self._request_times.append(now)
        return None
