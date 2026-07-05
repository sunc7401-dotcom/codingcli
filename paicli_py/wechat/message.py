"""微信消息模型 —— 对应 ``com.paicli.wechat.WechatMessage`` 和 ``WechatMediaItem``。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WechatMediaItem:
    type: str = ""
    file_name: str = ""
    mime_type: str = ""
    encrypt_query_param: str = ""
    aes_key: str = ""


@dataclass
class WechatMessage:
    message_id: str = ""
    from_user_id: str = ""
    context_token: str = ""
    text: str = ""
    media_items: list[WechatMediaItem] = field(default_factory=list)
