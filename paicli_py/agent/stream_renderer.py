"""流式渲染器 —— 在 Agent 运行期间处理 LLM 流式输出。

对应 ``com.paicli.agent.StreamRenderer``（Agent 内部类）。

负责：
- reasoning content 与 answer content 的分离显示
- 工具调用进度的实时展示
- 状态栏更新
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from paicli_py.llm.models import StreamListener

if TYPE_CHECKING:
    from paicli_py.render.protocol import Renderer


class AgentStreamRenderer(StreamListener):
    """包装 Renderer 的流式输出处理。

    自动识别 reasoning/content 切换，
    通过渲染器展示给用户。
    """

    def __init__(self, renderer: Renderer | None = None) -> None:
        self._renderer = renderer
        self._reasoning_started = False
        self._content_started = False
        self._reasoning_buffer: list[str] = []
        self._content_buffer: list[str] = []

    def on_reasoning_delta(self, delta: str) -> None:
        if not self._reasoning_started:
            self._reasoning_started = True
            if self._renderer:
                self._renderer.stream("💭 思考中...\n")
        self._reasoning_buffer.append(delta)
        if self._renderer:
            self._renderer.stream(delta)

    def on_content_delta(self, delta: str) -> None:
        if not self._content_started:
            self._content_started = True
            if self._renderer and self._reasoning_started:
                self._renderer.stream("\n\n---\n\n")
        self._content_buffer.append(delta)
        if self._renderer:
            self._renderer.stream(delta)

    @property
    def full_reasoning(self) -> str:
        return "".join(self._reasoning_buffer)

    @property
    def full_content(self) -> str:
        return "".join(self._content_buffer)

    def reset(self) -> None:
        """重置状态，准备下一轮流式输出。"""
        self._reasoning_started = False
        self._content_started = False
        self._reasoning_buffer.clear()
        self._content_buffer.clear()
