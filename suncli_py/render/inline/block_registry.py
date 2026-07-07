"""块注册表 —— 管理活跃的可折叠块。

对应 ``com.paicli.render.inline.BlockRegistry``。

核心设计：
- 双端队列，最新块在尾部
- 注册新块时冻结所有旧块（已滚出可视区）
- 只能切换最后一个（最新）块
"""

from __future__ import annotations

from collections import deque

from suncli_py.render.inline.foldable_block import FoldableBlock


class BlockRegistry:
    """可折叠块注册表。

    维护一个双端队列，最新块总是最后一个元素。
    注册新块时自动冻结所有旧块——只有最新块可被切换。
    """

    def __init__(self) -> None:
        self._blocks: deque[FoldableBlock] = deque()

    def register(self, block: FoldableBlock) -> None:
        """注册新块，冻结所有旧块。"""
        for b in self._blocks:
            b.freeze()
        self._blocks.append(block)

    def toggle_last(self) -> bool:
        """切换最后一个块的终端渲染。"""
        if not self._blocks:
            return False
        return self._blocks[-1].toggle()

    def toggle_last_for_redraw(self) -> None:
        """仅切换最后一个块的内存状态（用于重绘流程）。"""
        if self._blocks:
            self._blocks[-1].toggle_for_redraw()

    def freeze_all(self) -> None:
        """冻结所有块（正常输出恢复时调用）。"""
        for b in self._blocks:
            b.freeze()

    def clear(self) -> None:
        """清空所有块（/clear 命令时调用）。"""
        self._blocks.clear()

    def __len__(self) -> int:
        return len(self._blocks)
