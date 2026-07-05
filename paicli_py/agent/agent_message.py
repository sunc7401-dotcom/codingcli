"""Agent 间消息模型。

对应 ``com.paicli.agent.AgentMessage``。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AgentMessage:
    """多智能体系统中 Agent 间的通信消息。"""
    sender: str
    recipient: str
    content: str
    message_type: str = "task"  # task | result | feedback
