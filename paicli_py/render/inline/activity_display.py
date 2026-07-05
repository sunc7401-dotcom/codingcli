"""内联活动显示 —— 思考/工作状态的瞬态动画面板。

对应 ``com.paicli.render.inline.InlineActivityDisplay``。

核心设计：
- 固定高度（最多 4 行推理文本 + 1 行状态行）
- 旋转动画（braille 字符）
- 指数衰减进度条（1 - e^(-t/15s)）
- 自清理（结束或异常时擦除自身区域）
"""

from __future__ import annotations

import math
import sys
import time
from typing import ClassVar


class InlineActivityDisplay:
    """思考/活动瞬态面板。

    在终端内渲染并自行管理清屏，
    不依赖外部状态管理器。
    """

    # braille 旋转字符
    SPINNER_FRAMES: ClassVar[list[str]] = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    MAX_REASONING_CHARS = 4096
    MAX_REASONING_ROWS = 4

    def __init__(self) -> None:
        self._active = False
        self._label = ""
        self._start_ns = 0
        self._frame = 0
        self._rendered_rows = 0
        self._reasoning = ""
        self._show_cancel_hint = True

    @property
    def active(self) -> bool:
        return self._active

    def begin(self, label: str = "思考中...") -> None:
        """开始显示活动面板。"""
        self._active = True
        self._label = label
        self._start_ns = time.monotonic_ns()
        self._frame = 0
        self._rendered_rows = 0
        self._reasoning = ""

    def append_thinking(self, text: str) -> None:
        """追加推理文本。"""
        if not self._active:
            return
        self._reasoning += text
        if len(self._reasoning) > self.MAX_REASONING_CHARS:
            self._reasoning = self._reasoning[-self.MAX_REASONING_CHARS:]
        self._render()

    def end(self) -> None:
        """结束活动，擦除渲染区域。"""
        if not self._active:
            return
        self._active = False
        self._clear()
        self._rendered_rows = 0

    def tick(self) -> None:
        """推进动画帧（由外部定时器每 250ms 调用）。"""
        if not self._active:
            return
        self._frame = (self._frame + 1) % len(self.SPINNER_FRAMES)
        self._render()

    # ── 内部渲染 ────────────────────────────────────────────

    def _render(self) -> None:
        """渲染活动面板。先清除旧区域，再绘制新内容。"""
        self._clear()

        lines = self._build_lines()
        for line in lines:
            print(line)
        sys.stdout.flush()

        self._rendered_rows = len(lines)

    def _clear(self) -> None:
        """清除已渲染的行。"""
        if self._rendered_rows <= 0:
            return
        for _ in range(self._rendered_rows):
            sys.stdout.write("\033[F\033[2K")
        sys.stdout.flush()

    def _build_lines(self) -> list[str]:
        """构建显示行。"""
        lines: list[str] = []

        spinner = self.SPINNER_FRAMES[self._frame]
        elapsed = (time.monotonic_ns() - self._start_ns) / 1e9
        elapsed_str = f"{elapsed:.1f}s" if elapsed >= 1 else f"{int(elapsed * 1000)}ms"

        # 进度条
        progress = self._progress_percent()
        bar = self._progress_bar(progress)

        # 第一行: 旋转器 + 标签 + 进度条 + 耗时 + 取消提示
        line1 = f" {spinner} {self._label}  {bar} {elapsed_str}"
        if self._show_cancel_hint:
            line1 += "  [ESC 取消]"
        lines.append(line1)

        # 推理文本（最多 4 行）
        reasoning_lines = self._reasoning.splitlines()[-self.MAX_REASONING_ROWS:]
        for rl in reasoning_lines:
            lines.append(f"   \033[2m{rl[:120]}\033[0m")

        return lines

    @staticmethod
    def _progress_bar(percent: float) -> str:
        """渲染 ▰▱ 进度条。"""
        width = 10
        filled = max(0, min(width, int(percent / 100 * width)))
        return "▰" * filled + "▱" * (width - filled)

    def _progress_percent(self) -> float:
        """指数衰减进度（1 - e^(-t/15s)），1-95% 之间。"""
        elapsed = (time.monotonic_ns() - self._start_ns) / 1e9
        pct = (1 - math.exp(-elapsed / 15)) * 100
        return max(1.0, min(95.0, pct))
