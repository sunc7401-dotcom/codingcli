"""微信渲染器 —— 对应 ``com.paicli.wechat.WechatRenderer``。"""

from __future__ import annotations

import re

from paicli_py.render.status import StatusInfo


class WechatRenderer:
    """将 Agent 输出缓冲并格式化为微信消息的渲染器。

    实现 Renderer 协议用于微信 Agent 会话。
    """

    def __init__(self) -> None:
        self._buffer: list[str] = []
        self._status = StatusInfo()

    def start(self) -> None:
        pass

    def begin_turn(self, user_input: str) -> None:
        self._buffer.clear()

    def stream(self, text: str) -> None:
        self._buffer.append(text)

    def append_tool_calls(self, tool_calls: list) -> None:
        pass  # 微信消息中不展示工具调用详情

    def append_tool_result(self, tool_name: str, result: str) -> None:
        pass

    def append_diff(self, file_path: str, before: str, after: str) -> None:
        pass

    def update_status(self, status: StatusInfo) -> None:
        self._status = status

    def prompt_approval(self, request) -> bool:
        return True  # 微信模式下自动批准

    def finish_turn(self, final_answer: str) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def drain(self) -> str:
        """排空缓冲区，返回格式化的纯文本。"""
        text = "".join(self._buffer)
        # 去除 ANSI
        cleaned = re.sub(r"\033\[[0-9;]*[a-zA-Z]", "", text)
        self._buffer.clear()
        return cleaned.strip()
