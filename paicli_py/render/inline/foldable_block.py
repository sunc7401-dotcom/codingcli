"""可折叠块 —— Ctrl+O 切换折叠/展开的内联 UI 组件。

对应 ``com.paicli.render.inline.FoldableBlock``。

核心设计：
- 两个状态：collapsed（折叠，单行标题）和 expanded（展开，多行内容）
- 通过 ANSI cursor-up + CLEAR_TO_EOS 原地重绘切换
- 冻结（frozen）后不再可切换（块已滚出可视区）
"""

from __future__ import annotations

from paicli_py.render.inline.ansi_seq import CLEAR_TO_EOS, move_up


class FoldableBlock:
    """终端内的可折叠内容块。

    使用示例::

        block = FoldableBlock(
            collapsed_header="📄 读取了 3 个文件 (ctrl+o 展开)",
            expanded_lines=["file1.py: ...", "file2.py: ...", "file3.py: ..."],
            collapse_footer="收起 (ctrl+o)",
        )
        block.render_initial()
        # ...用户按 Ctrl+O...
        block.toggle()
    """

    def __init__(
        self,
        collapsed_header: str,
        expanded_lines: list[str],
        collapse_footer: str = "收起 (ctrl+o)",
    ) -> None:
        self._collapsed_header = collapsed_header
        self._expanded_lines = list(expanded_lines)
        self._collapse_footer = collapse_footer
        self._expanded = False
        self._rendered_line_count = 1
        self._frozen = False

    @property
    def expanded(self) -> bool:
        return self._expanded

    @property
    def frozen(self) -> bool:
        return self._frozen

    def freeze(self) -> None:
        """冻结块，禁止后续 toggle。"""
        self._frozen = True

    def render_initial(self) -> None:
        """首次渲染：打印折叠标题。"""
        print(self._collapsed_header)
        self._rendered_line_count = 1

    def toggle(self) -> bool:
        """切换折叠/展开状态。

        使用 ANSI 序列清除当前渲染区域，然后重绘。
        如果已冻结则无操作。

        Returns:
            True 表示成功切换，False 表示已冻结。
        """
        if self._frozen:
            return False

        # 清除当前渲染区域
        print(f"\r{move_up(self._rendered_line_count)}{CLEAR_TO_EOS}", end="")

        if self._expanded:
            # 切换为折叠
            print(self._collapsed_header)
            self._rendered_line_count = 1
        else:
            # 切换为展开
            for line in self._expanded_lines:
                print(line)
            print(self._collapse_footer)
            self._rendered_line_count = len(self._expanded_lines) + 1

        self._expanded = not self._expanded
        return True

    def toggle_for_redraw(self) -> None:
        """仅切换内存状态，不写终端（用于重绘流程）。"""
        self._expanded = not self._expanded
        self._rendered_line_count = len(self.current_lines())

    def current_lines(self) -> list[str]:
        """返回当前状态对应的行列表。"""
        if self._expanded:
            return self._expanded_lines + [self._collapse_footer]
        return [self._collapsed_header]
