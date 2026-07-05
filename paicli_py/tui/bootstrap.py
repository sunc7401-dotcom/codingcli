"""TUI 启动引导 —— 对应 ``com.paicli.tui.TuiBootstrap``。"""

from __future__ import annotations

import os


class TuiBootstrap:
    """检测环境并启动 Textual 全屏 TUI。"""

    @staticmethod
    def should_use_tui() -> bool:
        """判断是否应使用 TUI 模式。"""
        return (
            os.environ.get("PAICLI_RENDERER", "") in ("lanterna", "tui")
            or os.environ.get("PAICLI_TUI", "") == "true"
        )

    @staticmethod
    def launch() -> None:
        """启动 TUI 模式。"""
        try:
            import importlib.util
            if importlib.util.find_spec("textual"):
                print("🚀 启动 PaiCLI TUI 模式")
            else:
                raise ImportError
        except ImportError:
            print("⚠️ Textual 未安装，使用内联模式")
