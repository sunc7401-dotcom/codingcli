"""Plan-and-Execute Agent。

对应 ``com.paicli.agent.PlanExecuteAgent``。

流程：
1. 生成执行计划
2. 用户审核
3. 按序执行每个步骤
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from suncli_py.agent.agent import Agent
    from suncli_py.plan.execution_plan import ExecutionPlan


class ReviewDecision(str, Enum):
    EXECUTE = "execute"
    SUPPLEMENT = "supplement"  # 补充修改
    CANCEL = "cancel"


class PlanExecuteAgent:
    """Plan-and-Execute 模式的 Agent。

    先生成执行计划，经用户审核后逐步执行。
    """

    def __init__(self, agent: Agent) -> None:
        self._agent = agent
        self._current_plan: ExecutionPlan | None = None

    async def run(self, user_input: str) -> str:
        """完整执行一次 Plan-and-Execute 流程。

        1. 规划阶段
        2. 审核阶段
        3. 执行阶段
        """
        # 1. 生成计划
        plan_prompt = (
            f"请为以下任务生成一个详细的执行计划。\n\n"
            f"任务: {user_input}\n\n"
            f"输出格式:\n"
            f"## 执行计划\n"
            f"1. [步骤1描述]\n"
            f"2. [步骤2描述]\n"
            f"..."
        )

        plan_text = await self._agent.run(plan_prompt)
        logger.info(f"执行计划:\n{plan_text}")

        # 2. 用户审核（简化为自动批准）
        decision = ReviewDecision.EXECUTE

        if decision == ReviewDecision.CANCEL:
            return "计划已取消。"

        if decision == ReviewDecision.SUPPLEMENT:
            supplement = await self._agent.run(f"原始计划:\n{plan_text}\n\n请补充完善以上计划。")
            plan_text = supplement

        # 3. 逐步执行
        execution_prompt = (
            f"请按照以下计划逐步执行，每完成一步报告进度。\n\n"
            f"## 执行计划\n{plan_text}\n\n"
            f"## 原始任务\n{user_input}"
        )

        result = await self._agent.run(execution_prompt)

        # 4. 最终汇总
        summary_prompt = (
            f"任务执行完毕。请对执行结果进行总结。\n\n"
            f"原始任务: {user_input}\n"
            f"执行计划:\n{plan_text}\n"
            f"执行结果:\n{result}"
        )

        return await self._agent.run(summary_prompt)
