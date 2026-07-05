"""规划器 —— 使用 LLM 生成执行计划。

对应 ``com.paicli.plan.Planner``。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from paicli_py.llm.client import LlmClient


class Planner:
    """LLM 驱动的任务规划器。

    使用示例::

        planner = Planner(llm_client)
        plan = await planner.create_plan("重构用户认证模块")
    """

    PLANNING_PROMPT = """你是一个软件工程规划专家。请为以下任务生成一份详细的执行计划。

每步以 [STEP] 开头，包含以下信息：
- 步骤名称
- 步骤描述
- 预期产出

要求：
- 步骤之间逻辑清晰，依赖关系合理
- 每步的产出可验证
- 考虑边界情况和错误处理

任务: {task}"""

    def __init__(self, llm_client: LlmClient) -> None:
        self._llm_client = llm_client

    async def create_plan(self, task_description: str) -> list[dict]:
        """为任务生成执行计划。"""
        from paicli_py.llm.models import Message

        prompt = self.PLANNING_PROMPT.format(task=task_description)
        messages = [Message.user(prompt)]

        response = await self._llm_client.chat(messages)

        # 解析步骤
        return self._parse_steps(response.content)

    @staticmethod
    def _parse_steps(text: str) -> list[dict]:
        """从 LLM 输出中解析步骤。"""
        steps: list[dict] = []
        for line in text.splitlines():
            line = line.strip()
            if line.upper().startswith("[STEP]") or line.startswith("[STEP]"):
                steps.append({"name": line, "description": ""})
            elif line and line[0].isdigit() and ". " in line:
                parts = line.split(". ", 1)
                steps.append({"name": parts[1] if len(parts) > 1 else line, "description": ""})
        return steps
