"""微信安全策略决策结果 —— 对应 com.paicli.wechat.WechatPolicyDecision。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WechatPolicyDecision:
    allowed: bool = True
    reason: str = ""
