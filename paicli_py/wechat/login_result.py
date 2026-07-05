"""微信登录结果 —— 对应 ``com.paicli.wechat.WechatLoginResult``。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WechatLoginResult:
    success: bool
    token: str = ""
    account_id: str = ""
    error: str = ""
