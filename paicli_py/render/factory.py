"""渲染器工厂。

对应 ``com.paicli.render.RendererFactory``。

根据 PAICLI_RENDERER 环境变量选择渲染器：
- inline（默认）: Claude Code 风格内联渲染
- plain: 纯文本 stdout 输出
- lanterna / tui: 全屏 TUI（需要 textual）
"""

from __future__ import annotations

import os

from paicli_py.render.protocol import Renderer


class RendererFactory:
    """渲染器工厂。"""

    @staticmethod
    def resolve_mode() -> str:
        """解析渲染模式。"""
        return os.environ.get("PAICLI_RENDERER", "inline").lower().strip()

    @staticmethod
    def create(mode: str | None = None) -> Renderer:
        """根据模式创建渲染器。"""
        mode = (mode or RendererFactory.resolve_mode()).strip().lower()

        if mode in ("plain", "text", "simple"):
            from paicli_py.render.plain import PlainRenderer
            return PlainRenderer()

        if mode in ("lanterna", "tui"):
            # TUI 需要 textual 库，不可用时降级
            try:
                from paicli_py.tui.lanterna_renderer import LanternaRenderer
                return LanternaRenderer()
            except ImportError:
                pass

        # 默认：inline
        from paicli_py.render.inline_renderer import InlineRenderer
        return InlineRenderer()
