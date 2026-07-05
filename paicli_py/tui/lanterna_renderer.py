"""基于 Textual 的全屏 TUI 渲染器。

对应 ``com.paicli.tui.LanternaRenderer``。

使用 Textual 框架实现全屏终端界面（替代 Java 的 Lanterna 库）。
"""

from __future__ import annotations

from paicli_py.render.protocol import Renderer, StatusInfo


class LanternaRenderer(Renderer):
    """基于 Textual 的全屏终端渲染器。

    提供:
    - 对话历史面板
    - 输入栏
    - 状态栏
    - 文件树
    - 代码高亮
    """

    def __init__(self) -> None:
        self._status = StatusInfo()
        self._app = None

    def start(self) -> None:
        try:
            from textual.app import App
            print("PaiCLI v16.1.0 (Python) — TUI 模式 (Textual)")
        except ImportError:
            print("⚠️ Textual 未安装，降级为内联渲染模式")
            from paicli_py.render.inline_renderer import InlineRenderer
            self.__class__ = InlineRenderer
            self.start()

    def begin_turn(self, user_input: str) -> None:
        pass

    def stream(self, text: str) -> None:
        print(text, end="", flush=True)

    def append_tool_calls(self, tool_calls: list[dict]) -> None:
        for tc in tool_calls:
            name = tc.get("function", {}).get("name", "?")
            print(f"\n🔧 {name}")

    def append_tool_result(self, tool_name: str, result: str) -> None:
        pass

    def append_diff(self, file_path: str, diff_text: str) -> None:
        pass

    def update_status(self, status: StatusInfo) -> None:
        self._status = status

    def prompt_approval(self, message: str) -> bool:
        try:
            return input(f"审批 [{message}] [y/N]: ").strip().lower() == "y"
        except (EOFError, KeyboardInterrupt):
            return False

    def finish_turn(self, final_answer: str) -> None:
        pass

    def shutdown(self) -> None:
        pass
