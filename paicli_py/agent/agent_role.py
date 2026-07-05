"""Agent 角色枚举。

对应 ``com.paicli.agent.AgentRole``。
"""

from enum import Enum


class AgentRole(str, Enum):
    PLANNER = "planner"     # 规划者
    EXECUTOR = "executor"   # 执行者
    REVIEWER = "reviewer"   # 审核者
    WORKER = "worker"       # 通用工作者
