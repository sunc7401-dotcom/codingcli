"""LLM-backed compression for short-term entries and real message history."""

from __future__ import annotations

import uuid

from loguru import logger

from suncli_py.llm.client import LlmClient
from suncli_py.llm.models import Message
from suncli_py.memory.models import MemoryEntry, MemoryType, estimate_message_tokens
from suncli_py.memory.storage import ConversationMemory


class ContextCompressor:
    MAX_INPUT_CHARS = 60_000

    def __init__(self, client: LlmClient) -> None:
        self.client = client

    async def compress(self, memory: ConversationMemory) -> str | None:
        entries = memory.get_all()
        if len(entries) < 2:
            return None
        transcript = "\n\n".join(f"{entry.type.value}: {entry.content}" for entry in entries)
        prompt = (
            "请压缩以下短期记忆，保留用户目标、已完成操作、关键结论和待办。"
            "不要添加原文中不存在的事实，输出简洁中文摘要。\n\n" + transcript[: self.MAX_INPUT_CHARS]
        )
        try:
            response = await self.client.chat(
                messages=[Message.system("你是短期记忆摘要助手，只输出摘要。"), Message.user(prompt)]
            )
        except (OSError, RuntimeError) as err:
            logger.warning("Short-term memory compression failed: {}", err)
            return None
        summary = response.content.strip() if response else ""
        if not summary:
            return None
        memory.replace_with_summary(
            MemoryEntry(id=f"summary-{uuid.uuid4().hex[:8]}", content=summary, type=MemoryType.SUMMARY)
        )
        return summary


class ConversationHistoryCompactor:
    MAX_SUMMARY_INPUT_CHARS = 60_000

    def __init__(self, client: LlmClient, retain_recent_rounds: int = 3) -> None:
        self.client = client
        self.retain_recent_rounds = max(1, retain_recent_rounds)

    async def compact_if_needed(self, history: list[Message], trigger_tokens: int) -> bool:
        if estimate_message_tokens(history) < trigger_tokens:
            return False
        return await self._compact(history, self.retain_recent_rounds)

    async def compact_now(self, history: list[Message]) -> bool:
        return await self._compact(history, 1)

    async def _compact(self, history: list[Message], retain_rounds: int) -> bool:
        if not history:
            return False
        system_end = 1 if history[0].role == "system" else 0
        user_indices = [index for index in range(system_end, len(history)) if history[index].role == "user"]
        if len(user_indices) <= retain_rounds:
            return False
        split_index = user_indices[-retain_rounds]
        old_messages = history[system_end:split_index]
        if not old_messages:
            return False
        transcript = self._transcript(old_messages)
        prompt = (
            "请把下面的对话历史压缩成简明摘要，保留用户目标、已完成的关键操作、"
            "已达成结论以及未解决问题。不要复述无关闲聊，只输出 1-3 段中文摘要。\n\n"
            + transcript
        )
        try:
            response = await self.client.chat(
                messages=[Message.system("你是对话摘要助手，只输出摘要本身。"), Message.user(prompt)]
            )
        except (OSError, RuntimeError) as err:
            logger.warning("Conversation history compression failed: {}", err)
            return False
        summary = response.content.strip() if response else ""
        if not summary:
            return False
        history[:] = [
            *history[:system_end],
            Message.user("[已压缩的历史对话摘要]\n" + summary),
            Message.assistant("好的，我已了解之前的上下文，请继续。"),
            *history[split_index:],
        ]
        return True

    def _transcript(self, messages: list[Message]) -> str:
        chunks: list[str] = []
        size = 0
        for message in messages:
            chunk = f"{message.role.upper()}: {message.content}"
            for call in message.tool_calls or []:
                chunk += f"\n  TOOL_CALL {call.name}: {call.arguments}"
            if size + len(chunk) > self.MAX_SUMMARY_INPUT_CHARS:
                chunks.append("...(超长内容已截断)")
                break
            chunks.append(chunk)
            size += len(chunk)
        return "\n\n".join(chunks)
