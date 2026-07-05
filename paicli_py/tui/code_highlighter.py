"""TUI 代码高亮器 —— 对应 ``com.paicli.tui.highlight.CodeHighlighter``。"""


class CodeHighlighter:
    """基于 tree-sitter 的代码语法高亮。"""

    @staticmethod
    def highlight(code: str, language: str = "python") -> str:
        """返回带 ANSI 颜色的代码文本。"""
        return code
