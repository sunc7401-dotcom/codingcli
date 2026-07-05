"""ANSI 转义序列常量 —— 光标控制、清屏、滚动区域。

对应 ``com.paicli.render.inline.AnsiSeq``。
与 AnsiStyle（颜色/样式）分离，这里只处理结构性终端操作。
"""

from __future__ import annotations

ESC = "\033"

# ── 光标 ──
SAVE_CURSOR = ESC + "7"
RESTORE_CURSOR = ESC + "8"
HIDE_CURSOR = ESC + "[?25l"
SHOW_CURSOR = ESC + "[?25h"

# ── 清除 ──
CLEAR_LINE = ESC + "[2K"
CLEAR_TO_EOL = ESC + "[K"
CLEAR_TO_EOS = ESC + "[J"

# ── 滚动区域 ──
RESET_SCROLL_REGION = ESC + "[r"

# ── 反转 ──
REVERSE_ON = ESC + "[7m"
REVERSE_OFF = ESC + "[27m"

# ── 样式 ──
RESET = ESC + "[0m"
BOLD = ESC + "[1m"
DIM = ESC + "[2m"


def set_scroll_region(top: int, bottom: int) -> str:
    """设置滚动区域（1-based, 含边界）。"""
    return f"{ESC}[{top};{bottom}r"


def move_cursor(row: int, col: int) -> str:
    """移动光标到指定行列（1-based）。"""
    return f"{ESC}[{row};{col}H"


def move_up(n: int) -> str:
    """光标上移 n 行。"""
    return f"{ESC}[{n}A"


def move_down(n: int) -> str:
    """光标下移 n 行。"""
    return f"{ESC}[{n}B"
