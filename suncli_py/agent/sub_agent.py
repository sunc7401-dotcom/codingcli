"""子 Agent —— 轻量级 Agent 用于子任务。

对应 ``com.paicli.agent.SubAgent``。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from suncli_py.agent.agent import Agent
    from suncli_py.agent.agent_budget import AgentBudget
    from suncli_py.llm.client import LlmClient
    from suncli_py.tool.registry import ToolRegistry


class SubAgent:
    """轻量级子 Agent，共享父 Agent 的工具注册表。

    用于多智能体编排中的 Worker 角色。
    """

    def __init__(
        self,
        llm_client: LlmClient,
        tool_registry: ToolRegistry,
        role: str = "worker",
        budget: AgentBudget | None = None,
    ) -> None:
        from suncli_py.agent.agent import Agent
        from suncli_py.agent.agent_budget import AgentBudget

        self._agent = Agent(
            llm_client=llm_client,
            tool_registry=tool_registry,
            budget=budget or AgentBudget.from_context_window(llm_client.max_context_window),
        )
        self._role = role

    async def run(self, task: str) -> str:
        """执行子任务。"""
        self._agent.set_system_prompt(
            f"你是一个 {self._role} 角色。请高效完成分配给你的子任务。"
        )
        return await self._agent.run(task)

    @property
    def agent(self) -> Agent:
        return self._agent
