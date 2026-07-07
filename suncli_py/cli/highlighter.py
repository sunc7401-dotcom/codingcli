"""输入高亮器 —— 对应 ``com.paicli.cli.PaiCliHighlighter``。

对用户输入进行语法高亮：
- 斜杠命令 → 青色
- @提及 → 蓝色
- 危险模式 → 红色
- 敏感信息 → 黄色
"""

from __future__ import annotations

from prompt_toolkit.lexers import Lexer


class PaiCliHighlighter(Lexer):
    """语法高亮词法分析器。"""

    def lex_document(self, document):
        """对文档进行词法分析，返回 (style, text) 对。"""

        def get_line(lineno):
            line = document.lines[lineno]
            parts = []

            i = 0
            while i < len(line):
                # 斜杠命令
                if line[i] == "/":
                    j = i + 1
                    while j < len(line) and not line[j].isspace():
                        j += 1
                    parts.append(("class:slash-command", line[i:j]))
                    i = j
                # @提及
                elif line[i] == "@":
                    j = i + 1
                    while j < len(line) and not line[j].isspace():
                        j += 1
                    parts.append(("class:mention", line[i:j]))
                    i = j
                else:
                    # 查找下一个特殊字符
                    j = i + 1
                    while j < len(line) and line[j] not in "/@":
                        j += 1
                    parts.append(("", line[i:j]))
                    i = j

            return parts

        return get_line
