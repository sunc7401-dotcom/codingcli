"""ANSI 样式常量与辅助函数 —— 对应 ``com.paicli.util.AnsiStyle``。"""

from __future__ import annotations

import os

RESET = "\033[0m"; BOLD = "\033[1m"; DIM = "\033[2m"; ITALIC = "\033[3m"; UNDERLINE = "\033[4m"
BLACK = "\033[30m"; RED = "\033[31m"; GREEN = "\033[32m"; YELLOW = "\033[33m"; BLUE = "\033[34m"
MAGENTA = "\033[35m"; CYAN = "\033[36m"; WHITE = "\033[37m"
BRIGHT_BLACK = "\033[90m"; BRIGHT_RED = "\033[91m"; BRIGHT_GREEN = "\033[92m"
BRIGHT_YELLOW = "\033[93m"; BRIGHT_BLUE = "\033[94m"; BRIGHT_MAGENTA = "\033[95m"
BRIGHT_CYAN = "\033[96m"; BRIGHT_WHITE = "\033[97m"

def style(text: str, *codes: str) -> str:
    return "".join(codes) + text + RESET

# ── 禁用检查（与 Java isEnabled() 一致）─────────────────

def is_enabled() -> bool:
    """检查 ANSI 样式是否可用。

    检查顺序: paicli.render.color 属性 > NO_COLOR 环境变量 > TERM 环境变量
    """
    if os.environ.get("paicli.render.color", "").lower() in ("false", "0", "no"):
        return False
    if os.environ.get("NO_COLOR", ""):
        return False
    term = os.environ.get("TERM", "")
    if term == "dumb":
        return False
    return True

_ENABLED = is_enabled()

def _s(text: str, *codes: str) -> str:
    return style(text, *codes) if _ENABLED else text

# ── 样式方法（与 Java 完全对齐）─────────────────────────

def heading(text: str) -> str: return _s(text, BOLD, CYAN)
def section(text: str) -> str: return _s(text, BOLD, WHITE)
def answerMarker(text: str) -> str: return _s(text, GREEN)
def subtle(text: str) -> str: return _s(text, DIM)
def thinking(text: str) -> str: return _s(text, ITALIC, BRIGHT_BLACK)
def userMessageBlock(text: str) -> str:
    return _s(text, BLUE, "\033[47m")  # white bg + blue text
def codeLabel(text: str) -> str: return _s(text, YELLOW)
def error(text: str) -> str: return _s(text, RED)
def quotePrefix(text: str) -> str: return _s(text, DIM, ITALIC)
def emphasis(text: str) -> str: return _s(text, BOLD, WHITE)
def success(text: str) -> str: return _s(text, GREEN)
def warning(text: str) -> str: return _s(text, YELLOW)

# ── 显示宽度（CJK/emoji 感知）────────────────────────────

def display_width(s: str) -> int:
    """计算字符串在终端中的显示宽度。"""
    w = 0
    i = 0
    while i < len(s):
        cp = ord(s[i])
        if 0x1100 <= cp <= 0x115F or 0x2329 <= cp <= 0x232A or 0x2E80 <= cp <= 0xA4CF or \
           0xAC00 <= cp <= 0xD7A3 or 0xF900 <= cp <= 0xFAFF or 0xFE10 <= cp <= 0xFE19 or \
           0xFE30 <= cp <= 0xFE6F or 0xFF01 <= cp <= 0xFF60 or 0xFFE0 <= cp <= 0xFFE6 or \
           0x1F300 <= cp <= 0x1F64F or 0x1F680 <= cp <= 0x1F6FF or 0x2600 <= cp <= 0x26FF:
            w += 2
        elif cp >= 0x10000:
            w += 2; i += 1  # surrogate pair
        else:
            w += 1
        i += 1
    return w
