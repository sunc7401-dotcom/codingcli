"""微信更新模型 —— 对应 com.paicli.wechat.WechatUpdate。"""

from __future__ import annotations

from dataclasses import dataclass

from paicli_py.wechat.message import WechatMessage


@dataclass
class WechatUpdate:
    update_id: str = ""
    message: WechatMessage | None = None
