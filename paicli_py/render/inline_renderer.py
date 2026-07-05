"""Inline 渲染器 —— Claude Code 风格的内联终端渲染。

对应 ``com.paicli.render.inline.InlineRenderer``。

使用 rich 库实现：
- 可折叠的工具调用块
- 底部状态栏
- Diff 渲染
- Slash 命令面板
"""

from __future__ import annotations

from paicli_py.render.protocol import Renderer
from paicli_py.render.status import StatusInfo


class InlineRenderer(Renderer):
    """Claude Code 风格的内联渲染器。

    使用 rich 的 Live display 实现流式输出和状态更新。
    """

    def __init__(self) -> None:
        self._status = StatusInfo()

    def start(self) -> None:
        from rich.console import Console
        self._console = Console()
        self._console.print("[bold cyan]PaiCLI v16.1.0[/bold cyan] (Python) - 内联渲染模式")
        self._console.print("[dim]输入 /help 查看可用命令[/dim]\n")

    def begin_turn(self, user_input: str) -> None:
        self._console.print()

    def stream(self, text: str) -> None:
        self._console.print(text, end="", highlight=False)

    def append_tool_calls(self, tool_calls: list[dict]) -> None:
        self._console.print()
        for tc in tool_calls:
            name = tc.get("function", {}).get("name", tc.name if hasattr(tc, "name") else "?")
            self._console.print(f"[yellow]🔧 {name}[/yellow]")

    def append_tool_result(self, tool_name: str, result: str) -> None:
        _preview = result[:300] + "..." if len(result) > 300 else result
        self._console.print(f"[dim]📋 [{tool_name}][/dim]")

    def append_diff(self, file_path: str, diff_text: str) -> None:
        self._console.print(f"[green]📝 {file_path}[/green]")

    def update_status(self, status: StatusInfo) -> None:
        self._status = status

    def prompt_approval(self, message: str) -> bool:
        self._console.print(f"\n[bold yellow]⚠️  审批: {message}[/bold yellow]")
        try:
            choice = input("[y/N] ").strip().lower()
            return choice == "y"
        except (EOFError, KeyboardInterrupt):
            return False

    def finish_turn(self, final_answer: str) -> None:
        self._console.print()

    def shutdown(self) -> None:
        self._console.print("\n[dim]再见！[/dim]")
