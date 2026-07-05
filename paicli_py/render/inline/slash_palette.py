"""斜杠命令面板 —— 浮动选择列表，支持方向键和数字快捷键。

对应 ``com.paicli.render.inline.SlashPalette``。

核心设计：
- 在光标位置渲染一个临时浮动面板
- 支持 ↑↓ 选择、Enter 确认、ESC 取消、1-9 快速选择
- 退出时使用 ANSI 序列擦除面板
"""

from __future__ import annotations

import sys
import termios
import tty
from typing import Any


class SlashPalette:
    """临时浮动选择面板。"""

    # 特殊键码
    KEY_ESC = -2
    KEY_UP = -3
    KEY_DOWN = -4

    def __init__(self) -> None:
        self._items: list[str] = []
        self._selected: int = 0
        self._rendered_lines: int = 0

    def open(self, title: str, items: list[str]) -> str | None:
        """打开面板并阻塞等待用户选择。

        Returns:
            选中的项，取消返回 None。
        """
        self._items = items
        self._selected = 0

        try:
            while True:
                self._rendered_lines = self._render(title)
                key = self._read_key()

                self._erase()

                if key == self.KEY_ESC or key == -1:
                    return None
                elif key == ord("\r") or key == ord("\n"):
                    return items[self._selected] if items else None
                elif key == self.KEY_UP or key == ord("k"):
                    self._selected = max(0, self._selected - 1)
                elif key == self.KEY_DOWN or key == ord("j"):
                    self._selected = min(len(items) - 1, self._selected + 1)
                elif ord("1") <= key <= ord("9"):
                    idx = key - ord("1")
                    if idx < len(items):
                        return items[idx]
        finally:
            self._erase()

    # ── 渲染 ────────────────────────────────────────────────

    def _render(self, title: str) -> int:
        """渲染面板，返回占用的终端行数。"""
        lines: list[str] = []
        lines.append(f"\033[1m{title}\033[0m")

        for i, item in enumerate(self._items):
            prefix = "▶" if i == self._selected else " "
            num_hint = f"{i + 1}" if i < 9 else " "
            lines.append(f" {prefix} {num_hint} {item}")

        lines.append("↑↓ 选择  Enter 确认  ESC 取消  1-9 快速选择")

        text = "\n".join(lines)
        print(text, flush=True)
        return len(lines)

    def _erase(self) -> None:
        """擦除面板。"""
        if self._rendered_lines <= 0:
            return
        # 上移并清屏
        for _ in range(self._rendered_lines):
            sys.stdout.write("\033[F\033[2K")
        sys.stdout.flush()

    # ── 单键读取 ────────────────────────────────────────────

    @staticmethod
    def _read_key() -> int:
        """读取单键（raw mode）。"""
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\033":
                # ESC 序列
                ch2 = sys.stdin.read(1)
                if ch2 == "[":
                    ch3 = sys.stdin.read(1)
                    if ch3 == "A":
                        return SlashPalette.KEY_UP
                    elif ch3 == "B":
                        return SlashPalette.KEY_DOWN
                return SlashPalette.KEY_ESC
            return ord(ch) if ch else -1
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
