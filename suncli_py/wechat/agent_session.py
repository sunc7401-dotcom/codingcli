"""微信 Agent 会话 —— 对应 ``com.paicli.wechat.WechatAgentSession``。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from suncli_py.agent.agent import Agent


class WechatAgentSession:
    """为微信消息创建 Agent 会话并执行任务。

    管理运行状态、取消和上下文压缩。
    """

    def __init__(self, agent: Agent) -> None:
        self._agent = agent
        self._running = False
        self._current_task: Any = None

    @property
    def running(self) -> bool:
        return self._running

    async def submit(self, user_id: str, prompt: str) -> str:
        """提交用户消息给 Agent 执行。"""
        self._running = True
        try:
            result = await self._agent.run(f"[微信用户 {user_id}]\n{prompt}")
            return result
        except Exception as e:
            logger.error(f"微信 Agent 执行异常: {e}")
            return f"处理异常: {e}"
        finally:
            self._running = False

    def cancel(self) -> None:
        """取消当前执行。"""
        self._running = False
