"""终端 Markdown 渲染器 —— 对应 ``com.paicli.util.TerminalMarkdownRenderer``。

提供流式 append/finish API 和静态 render 方法。
"""

from __future__ import annotations


class TerminalMarkdownRenderer:
    """流式终端 Markdown 渲染器。

    使用方式:
        r = TerminalMarkdownRenderer(80)
        r.append("# 标题\n正文...\n")
        result = r.finish()
    """

    def __init__(self, columns: int = 80) -> None:
        self._columns = columns
        self._buffer: list[str] = []
        self._pending: str = ""

    def append(self, chunk: str) -> None:
        """追加 Markdown 文本块（流式）。"""
        self._pending += chunk
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            self._buffer.append(self._render_line(line))

    def finish(self) -> str:
        """完成流式渲染，返回 ANSI 文本。"""
        if self._pending:
            self._buffer.append(self._render_line(self._pending))
            self._pending = ""
        return "\n".join(self._buffer)

    def _render_line(self, line: str) -> str:
        s = line.strip()
        if s.startswith("# "): return f"\033[1;36m{s}\033[0m"
        if s.startswith("## "): return f"\033[1;36m{s}\033[0m"
        if s.startswith("> "): return f"\033[2;3m{s}\033[0m"
        if s.startswith("```"): return f"\033[33m{s}\033[0m"
        if s.startswith("- ") or s.startswith("* "): return f"  \033[32m•\033[0m {s[2:]}"
        return line

    @staticmethod
    def render(markdown_text: str, columns: int = 80) -> str:
        """一次性渲染完整 Markdown。"""
        r = TerminalMarkdownRenderer(columns)
        r.append(markdown_text)
        return r.finish()
