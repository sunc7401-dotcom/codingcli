"""输入历史管理器 —— 对应 ``com.paicli.cli.PaiCliHistory``。

过滤敏感信息（API Key、base64 图片等）不写入历史。
"""

from __future__ import annotations

import re

from prompt_toolkit.history import FileHistory, History


class PaiCliHistory(History):
    """带敏感信息过滤的输入历史。

    继承 prompt_toolkit 的 FileHistory，
    在写入前过滤掉 API Key 和 base64 图片等敏感内容。
    """

    # 敏感信息模式
    _SECRET_PATTERNS = [
        re.compile(r'(?:api[_-]?key|apikey|secret|token|password)\s*[=:]\s*\S+', re.IGNORECASE),
        re.compile(r'[A-Za-z0-9+/]{100,}={0,2}'),  # 长 base64
    ]

    # 最大行长度
    MAX_LINE_LENGTH = 10_000

    def __init__(self, filename: str) -> None:
        self._history = FileHistory(filename)

    def append_string(self, string: str) -> None:
        """追加历史记录（过滤敏感信息）。"""
        if len(string) > self.MAX_LINE_LENGTH:
            return

        filtered = self._filter_secrets(string)
        self._history.append_string(filtered)

    def _filter_secrets(self, text: str) -> str:
        """替换敏感信息为 ***。"""
        for pattern in self._SECRET_PATTERNS:
            text = pattern.sub("***", text)
        return text

    def __getattr__(self, name):
        return getattr(self._history, name)
