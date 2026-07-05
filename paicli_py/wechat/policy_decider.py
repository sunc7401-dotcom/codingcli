"""微信安全策略决策器 —— 对应 ``com.paicli.wechat.WechatPolicyDecider``。"""

from __future__ import annotations

from dataclasses import dataclass

from paicli_py.wechat.policy_config import WechatPolicyConfig


@dataclass
class WechatPolicyDecision:
    allowed: bool
    reason: str = ""


class WechatPolicyDecider:
    """根据配置判断微信消息是否允许执行。"""

    def __init__(self, config: WechatPolicyConfig) -> None:
        self._config = config
        self._message_count: dict[str, int] = {}

    def check(self, user_id: str, message_text: str) -> WechatPolicyDecision:
        # 黑名单
        if user_id in self._config.blocked_users:
            return WechatPolicyDecision(allowed=False, reason="用户已被屏蔽")
        # 白名单
        if self._config.allowed_users and user_id not in self._config.allowed_users:
            return WechatPolicyDecision(allowed=False, reason="用户不在白名单中")
        # 速率限制
        count = self._message_count.get(user_id, 0)
        if count >= self._config.max_messages_per_hour:
            return WechatPolicyDecision(allowed=False, reason=f"超过每小时消息上限 ({self._config.max_messages_per_hour})")
        self._message_count[user_id] = count + 1
        # Token 限制
        if len(message_text) > self._config.max_tokens_per_message * 2:
            return WechatPolicyDecision(allowed=False, reason=f"消息过长 ({len(message_text)} 字符)")
        return WechatPolicyDecision(allowed=True)
