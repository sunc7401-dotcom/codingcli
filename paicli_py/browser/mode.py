"""浏览器会话模式 —— 对应 ``com.paicli.browser.BrowserMode``。"""

from enum import Enum


class BrowserMode(str, Enum):
    ISOLATED = "isolated"
    SHARED = "shared"
