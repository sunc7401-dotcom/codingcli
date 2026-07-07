"""TUI 会话控制器 —— 对应 ``com.paicli.tui.TuiSessionController``。"""

from __future__ import annotations


class TuiSessionController:
    """管理 TUI 会话的生命周期和消息路由。"""

    def __init__(self) -> None:
        self._messages: list[dict] = []

    def add_message(self, role: str, content: str) -> None:
        self._messages.append({"role": role, "content": content})

    def clear(self) -> None:
        self._messages.clear()

    @property
    def messages(self) -> list[dict]:
        return list(self._messages)
