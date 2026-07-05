"""底部状态栏 —— 显示模型、token 用量、模式、成本等信息。

对应 ``com.paicli.render.inline.BottomStatusBar``。

两行布局：
- 第一行: 模式 (YOLO/HITL) + 环境摘要 (MCP/Skills)
- 第二行: 模型 | 阶段 | 上下文用量条 | Token 计数 | 成本 | 耗时 | CWD
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import ClassVar

from paicli_py.render.protocol import StatusInfo

# 上下文用量条宽度
CONTEXT_BAR_WIDTH = 8


class BottomStatusBar:
    """底部状态栏渲染器。

    使用 rich 或纯 ANSI 实现。
    """

    def __init__(self) -> None:
        self._current: StatusInfo = StatusInfo()
        self._started = False
        self._start_time = time.time()
        self._mcp_summary: str | None = None
        self._skill_summary: str | None = None

    # ── 生命周期 ────────────────────────────────────────────

    def start(self) -> None:
        self._started = True
        self._start_time = time.time()

    def update(self, status: StatusInfo, mcp_summary: str | None = None, skill_summary: str | None = None) -> None:
        """更新状态（环境摘要会在后续更新中延续）。"""
        # 延续之前的 MCP/Skill 摘要如果新状态没有携带
        if mcp_summary is not None:
            self._mcp_summary = mcp_summary
        if skill_summary is not None:
            self._skill_summary = skill_summary

        self._current = status

    def close(self) -> None:
        self._started = False

    # ── 格式化 ──────────────────────────────────────────────

    def render(self) -> str:
        """渲染状态栏为 ANSI 字符串。"""
        width = os.get_terminal_size().columns
        return self._format_status_lines(width)

    def _format_status_lines(self, width: int) -> str:
        """格式化两行状态栏。"""
        status = self._current
        elapsed = time.time() - self._start_time

        # 第一行: 模式 + 环境
        mode = "🔓 YOLO" if status.hitl != "on" else "🔒 HITL"
        env_parts: list[str] = []
        if self._mcp_summary:
            env_parts.append(f"MCP {self._mcp_summary}")
        if self._skill_summary:
            env_parts.append(f"Skill {self._skill_summary}")
        env = " | ".join(env_parts) if env_parts else ""

        # 上下文用量条
        gauge = self._context_gauge(status)
        bar = "▰" * gauge["filled"] + "▱" * gauge["empty"]

        # CWD（缩短路径）
        cwd = self._compact_cwd()

        line1 = self._fit(f"{mode}  {env}", width)
        line2 = self._fit(
            f"{status.model} | {status.phase} | [{bar}] {status.tokens} | {self._format_elapsed(elapsed)} | {cwd}",
            width,
        )

        return f"\033[2m{line1}\n{line2}\033[0m"

    # ── 辅助 ────────────────────────────────────────────────

    @staticmethod
    def _context_gauge(status: StatusInfo) -> dict:
        """计算上下文用量条。"""
        try:
            parts = status.tokens.split("/")
            if len(parts) >= 2:
                used = int(parts[0].replace(",", "").replace("k", "000"))
                total = int(parts[1].split()[0].replace(",", "").replace("k", "000"))
            else:
                return {"filled": 0, "empty": CONTEXT_BAR_WIDTH}
        except (ValueError, IndexError):
            return {"filled": 0, "empty": CONTEXT_BAR_WIDTH}

        if total <= 0:
            return {"filled": 0, "empty": CONTEXT_BAR_WIDTH}

        ratio = min(1.0, used / total)
        filled = max(0, int(ratio * CONTEXT_BAR_WIDTH))
        return {"filled": filled, "empty": CONTEXT_BAR_WIDTH - filled}

    @staticmethod
    def _compact_cwd() -> str:
        """缩短 CWD 路径（将 home 替换为 ~）。"""
        cwd = str(Path.cwd())
        home = str(Path.home())
        if cwd.startswith(home):
            cwd = "~" + cwd[len(home):]
        return cwd

    @staticmethod
    def _format_elapsed(elapsed: float) -> str:
        """格式化耗时。"""
        if elapsed < 1:
            return f"{int(elapsed * 1000)}ms"
        return f"{elapsed:.1f}s"

    @staticmethod
    def _fit(text: str, width: int) -> str:
        """截断或填充到目标宽度。"""
        if len(text) > width:
            return text[:width - 3] + "..."
        return text.ljust(width)
