"""微信安全策略配置 —— 对应 ``com.paicli.wechat.WechatPolicyConfig``。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WechatPolicyConfig:
    max_messages_per_hour: int = 50
    max_tokens_per_message: int = 4000
    allowed_users: list[str] = field(default_factory=list)
    blocked_users: list[str] = field(default_factory=list)
