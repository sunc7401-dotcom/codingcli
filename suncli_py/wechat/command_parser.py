"""微信命令解析器 —— 对应 ``com.paicli.wechat.WechatCommandParser``。"""

from __future__ import annotations


class WechatCommandParser:
    """解析微信消息中的斜杠命令。"""

    COMMANDS = {
        "/help": "显示帮助",
        "/clear": "清空对话历史",
        "/compact": "压缩上下文",
        "/model": "切换/查看模型",
        "/cwd": "查看当前工作目录",
        "/status": "查看状态",
        "/send": "发送消息",
        "/pause": "暂停",
        "/resume": "恢复",
        "/stop": "停止",
    }

    @classmethod
    def parse(cls, text: str) -> tuple[str | None, str]:
        """解析命令。

        Returns:
            (command_name, payload) — 如果不是命令，command_name 为 None。
        """
        text = text.strip()
        if not text.startswith("/"):
            return None, text
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        if cmd in cls.COMMANDS:
            return cmd, parts[1] if len(parts) > 1 else ""
        return None, text

    @classmethod
    def is_bypass_command(cls, text: str) -> bool:
        """判断是否为旁路命令（不需要经过 Agent 处理）。"""
        cmd, _ = cls.parse(text)
        return cmd in ("/help", "/status", "/cwd", "/pause", "/resume", "/stop", "/model")

    @classmethod
    def help_text(cls) -> str:
        lines = ["可用命令:"]
        for cmd, desc in cls.COMMANDS.items():
            lines.append(f"  {cmd} — {desc}")
        return "\n".join(lines)
