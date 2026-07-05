"""多智能体编排器 —— Planner + Executor + Reviewer。

对应 ``com.paicli.agent.AgentOrchestrator``。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from paicli_py.agent.agent import Agent


class AgentOrchestrator:
    """多智能体编排器。

    团队组成：
    - Planner: 生成执行计划
    - Executor Workers: 并行执行各步骤
    - Reviewer: 审核执行结果
    """

    def __init__(self, planner: Agent, executor: Agent, reviewer: Agent | None = None) -> None:
        self._planner = planner
        self._executor = executor
        self._reviewer = reviewer

    async def run(self, user_input: str) -> str:
        """多智能体协作完成任务。

        1. Planner 生成计划
        2. Executor 逐步执行
        3. Reviewer 审核（可选）
        """
        # 1. 规划
        plan_result = await self._planner.run(
            f"请为以下任务制定一个分步执行计划，每步以 [STEP] 开头:\n\n{user_input}"
        )

        # 2. 提取步骤并执行
        steps = self._extract_steps(plan_result)
        if not steps:
            # 降级为直接执行
            return await self._executor.run(user_input)

        logger.info(f"编排器: {len(steps)} 个步骤待执行")

        # 3. 逐步执行
        results: list[str] = []
        for i, step in enumerate(steps, 1):
            logger.info(f"执行步骤 {i}/{len(steps)}: {step[:80]}...")
            result = await self._executor.run(f"执行以下步骤 ({i}/{len(steps)}):\n{step}")
            results.append(f"[步骤 {i} 结果]\n{result}")

        # 4. 汇总
        combined = "\n\n".join(results)
        if self._reviewer:
            review_result = await self._reviewer.run(
                f"请审核以下任务执行结果:\n\n"
                f"原始任务: {user_input}\n\n"
                f"执行结果:\n{combined}"
            )
            return review_result

        return combined

    @staticmethod
    def _extract_steps(text: str) -> list[str]:
        """从 Planner 输出中提取 [STEP] 开头的步骤。"""
        steps: list[str] = []
        for line in text.splitlines():
            line = line.strip()
            if line.upper().startswith("[STEP]") or line.startswith("[STEP]") or line and (line[0].isdigit() and (". " in line or "、" in line)):
                steps.append(line)
        return steps
