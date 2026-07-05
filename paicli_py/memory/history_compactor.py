"""对话历史压缩器 —— 压缩 Agent 主循环的 conversationHistory。

对应 ``com.paicli.memory.ConversationHistoryCompactor``。

算法：
1. 估算 conversationHistory 当前 token，未达 trigger 直接返回
2. 找出所有 user message 的索引；保留最近 retainRecentRounds 个 user 起算的尾部
3. 把 system 之后、splitIdx 之前的全部消息喂给 LLM 摘要
4. 重建: [system] + [user("[已压缩的历史对话摘要]\\n" + summary)] + [assistant("好的，已了解上下文。请继续。")] + [尾部保留消息]

关键约束：分割点必然落在 user message 边界，避免切断 tool_call / tool_result 的成对协议。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from paicli_py.llm.client import LlmClient
    from paicli_py.llm.models import Message

logger = logging.getLogger(__name__)

DEFAULT_RETAIN_RECENT_ROUNDS = 3
MAX_SUMMARY_INPUT_CHARS = 60_000

SUMMARY_PROMPT = """请把下面的对话历史压缩成简明摘要，保留：
1. 用户提出的关键诉求与目标
2. Agent 已经完成的关键操作（哪些工具调用了什么、返回了什么核心结果）
3. 已经达成的共识或结论
4. 仍未解决的问题或待办

不要复述每条原文，不要列举所有工具调用，不要保留无关闲聊。
输出 1-3 段中文，不要用列表，不要加任何前缀或元描述。

=== 待压缩的对话 ===
%s
=== 待压缩的对话（结束）===
"""


class ConversationHistoryCompactor:
    """压缩 ReAct 主循环里的 conversationHistory（List<Message>）。"""

    def __init__(self, llm_client: LlmClient | None = None, retain_recent_rounds: int = DEFAULT_RETAIN_RECENT_ROUNDS) -> None:
        self._llm_client = llm_client
        self._retain_recent_rounds = max(1, retain_recent_rounds)

    def set_llm_client(self, llm_client: LlmClient) -> None:
        self._llm_client = llm_client

    @property
    def retain_recent_rounds(self) -> int:
        return self._retain_recent_rounds

    def compact_if_needed(self, history: list[Message], trigger_tokens: int) -> bool:
        """评估并按需压缩 history，原地修改。"""
        return self._compact(history, trigger_tokens, force=False, retain_rounds=self._retain_recent_rounds)

    def compact_now(self, history: list[Message]) -> bool:
        """手动压缩 history，跳过 token 阈值判断。"""
        return self._compact(history, 0, force=True, retain_rounds=1)

    def compact(self, history: list[Message], keep_recent: int = 10) -> list[Message]:
        """简化的压缩入口（兼容旧 API）。"""
        self._compact(history, 0, force=True, retain_rounds=min(keep_recent, len(history)))
        return history

    def _compact(self, history: list[Message], trigger_tokens: int, force: bool, retain_rounds: int) -> bool:
        if not history:
            return False

        from paicli_py.memory.token_budget import TokenBudget
        current_tokens = TokenBudget.estimate_messages_tokens(history)
        if not force and current_tokens < trigger_tokens:
            return False

        # system 结束位置
        system_end = 1 if history and history[0].role == "system" else 0

        # 找出所有 user message 索引
        user_indices = [i for i in range(system_end, len(history)) if history[i].role == "user"]
        effective_retain = max(1, retain_rounds)

        if len(user_indices) <= effective_retain:
            logger.info(f"compactIfNeeded skip: only {len(user_indices)} user turns, < retain {effective_retain}")
            return False

        split_idx = user_indices[len(user_indices) - effective_retain]
        if split_idx <= system_end:
            return False

        old_msgs = history[system_end:split_idx]
        if not old_msgs:
            return False

        # 调 LLM 摘要
        summary = self._summarize(old_msgs)
        if not summary or not summary.strip():
            logger.warning("conversation summary returned empty; skip compaction")
            return False

        # 重建
        rebuilt = history[:system_end]
        rebuilt.append(type(history[0]).user("[已压缩的历史对话摘要]\n" + summary.strip()))
        rebuilt.append(type(history[0]).assistant("好的，我已了解之前的上下文，请继续。"))
        rebuilt.extend(history[split_idx:])

        after_tokens = TokenBudget.estimate_messages_tokens(rebuilt)
        history.clear()
        history.extend(rebuilt)
        logger.info(
            f"compacted conversationHistory: tokens {current_tokens} -> {after_tokens}, "
            f"messages ~{len(user_indices) + system_end} -> {len(rebuilt)}, summary chars {len(summary)}"
        )
        return True

    def _summarize(self, messages: list[Message]) -> str | None:
        """真正调 LLM 摘要。"""
        if self._llm_client is None:
            return self._simple_summarize(messages)

        from paicli_py.llm.models import Message as Msg
        parts: list[str] = []
        for m in messages:
            role = m.role.upper()
            line = f"{role}: {m.content or ''}"
            if m.tool_calls:
                for tc in m.tool_calls:
                    line += f"\n  TOOL_CALL {tc.name}: {tc.arguments}"
            parts.append(line + "\n")
            if sum(len(p) for p in parts) > MAX_SUMMARY_INPUT_CHARS:
                parts.append("...(超长内容已截断)\n")
                break

        prompt = SUMMARY_PROMPT % "".join(parts)
        req = [
            Msg.system("你是一个对话摘要助手，只输出摘要本身，不输出元描述。"),
            Msg.user(prompt),
        ]
        try:
            import asyncio
            response = asyncio.get_event_loop().run_until_complete(self._llm_client.chat(req, None))
            return response.content if response else None
        except Exception as e:
            logger.warning(f"conversation summary LLM call failed: {e}")
            return self._simple_summarize(messages)

    @staticmethod
    def _simple_summarize(messages: list[Message]) -> str:
        """降级摘要（无需 LLM）。"""
        lines: list[str] = []
        for m in messages[:10]:
            prefix = {"user": "用户", "assistant": "助手", "tool": "工具", "system": "系统"}.get(m.role, m.role)
            content = (m.content or "")[:200]
            lines.append(f"[{prefix}] {content}")
        return "对话摘要:\n" + "\n".join(lines)
