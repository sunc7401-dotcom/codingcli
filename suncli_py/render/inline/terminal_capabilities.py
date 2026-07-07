"""终端能力检测 —— 判断 ANSI、滚动区域、TrueColor 支持。

对应 ``com.paicli.render.inline.TerminalCapabilities``。

保守检测策略：能力足够时启用，不足时优雅降级。
"""

from __future__ import annotations

import os


def supports_ansi() -> bool:
    """检查终端是否支持 ANSI 转义序列。

    NO_COLOR 环境变量不影响光标控制，仅影响颜色。
    """
    term = os.environ.get("TERM", "")
    if term == "dumb":
        return False
    return True


def supports_scroll_region() -> bool:
    """检查终端是否支持滚动区域（DECSTBM）。

    需要:
    - ANSI 支持
    - 未设置 PAICLI_NO_STATUSBAR
    - 终端尺寸 >= 5 行 × 20 列
    """
    if not supports_ansi():
        return False

    if os.environ.get("PAICLI_NO_STATUSBAR"):
        return False

    try:
        size = os.get_terminal_size()
        return size.lines >= 5 and size.columns >= 20
    except (ValueError, OSError):
        return True  # 乐观假设


def supports_truecolor() -> bool:
    """检查终端是否支持 TrueColor (24-bit)。"""
    colorterm = os.environ.get("COLORTERM", "")
    return colorterm in ("truecolor", "24bit")


def safe_size() -> tuple[int, int]:
    """安全获取终端尺寸，失败时返回 80×24。"""
    try:
        size = os.get_terminal_size()
        return (size.columns, size.lines)
    except (ValueError, OSError):
        return (80, 24)
