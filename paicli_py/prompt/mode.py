"""提示词模式枚举 —— 与 Java 完全一致（6 个值）。

对应 ``com.paicli.prompt.PromptMode``。
"""

from enum import Enum


class PromptMode(str, Enum):
    """每种模式关联一个 prompt 资源文件名。"""
    AGENT = "agent"               # 默认的 Agent 模式
    PLAN = "plan"                 # Plan-and-Execute 的规划阶段
    PLANNER = "planner"           # 多 Agent 编排中的 Planner 角色
    TEAM_PLANNER = "team_planner" # 团队模式下的规划者
    TEAM_WORKER = "team_worker"   # 团队模式下的执行 Worker
    TEAM_REVIEWER = "team_reviewer"  # 团队模式下的审核者

    @property
    def resource_path(self) -> str:
        """对应的 Markdown 模板文件名。"""
        paths = {
            PromptMode.AGENT: "modes/agent.md",
            PromptMode.PLAN: "modes/plan.md",
            PromptMode.PLANNER: "modes/planner.md",
            PromptMode.TEAM_PLANNER: "modes/team_planner.md",
            PromptMode.TEAM_WORKER: "modes/team_worker.md",
            PromptMode.TEAM_REVIEWER: "modes/team_reviewer.md",
        }
        return paths.get(self, "")
