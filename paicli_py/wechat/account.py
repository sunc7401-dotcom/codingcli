"""微信账号模型 —— 对应 ``com.paicli.wechat.WechatAccount`` record。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WechatAccount:
    token: str
    account_id: str
    base_url: str = "https://ilink.weixin.qq.com"
    bound_user_id: str = ""
    workspace: str = ""
    sync_buf: str = ""
    created_at: str = ""
