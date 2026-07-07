"""微信文本格式化器 —— 对应 ``com.paicli.wechat.WechatTextFormatter``。"""

from __future__ import annotations


class WechatTextFormatter:
    """将 Agent 输出格式化为适合微信消息的纯文本。

    去除 ANSI 转义码，截断过长消息（微信限制约 3800 字符）。
    """

    MAX_CHARS = 3800

    @classmethod
    def format(cls, text: str) -> str:
        """格式化 Agent 输出文本。"""
        # 去除 ANSI 转义码
        import re
        cleaned = re.sub(r"\033\[[0-9;]*[a-zA-Z]", "", text)
        # 截断过长消息
        if len(cleaned) > cls.MAX_CHARS:
            cleaned = cleaned[:cls.MAX_CHARS - 20] + "\n\n...(已截断)"
        return cleaned.strip()

    @classmethod
    def split_long_message(cls, text: str) -> list[str]:
        """将超长消息拆分为多条（每条约 3800 字符）。"""
        cleaned = cls.format(text)
        if len(cleaned) <= cls.MAX_CHARS:
            return [cleaned]
        chunks: list[str] = []
        for i in range(0, len(cleaned), cls.MAX_CHARS):
            chunks.append(cleaned[i:i + cls.MAX_CHARS])
        return chunks
