"""Facade combining short-term, long-term, project, and compression memory."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from suncli_py.llm.client import LlmClient
from suncli_py.llm.models import Message
from suncli_py.memory.compression import ContextCompressor, ConversationHistoryCompactor
from suncli_py.memory.models import ContextProfile, MemoryEntry, MemoryType
from suncli_py.memory.project import ProjectMemoryLoader
from suncli_py.memory.storage import ConversationMemory, LongTermMemory, tokenize


class MemoryRetriever:
    def __init__(self, long_term: LongTermMemory) -> None:
        self.long_term = long_term

    def retrieve_long_term(self, query: str, limit: int, project_key: str) -> list[MemoryEntry]:
        query_lower = query.lower().strip()
        query_words = tokenize(query_lower)
        now = datetime.now(UTC)
        scored: list[tuple[float, MemoryEntry]] = []
        for entry in self.long_term.get_all(project_key):
            content = entry.content.lower()
            if query_lower and query_lower in content:
                score = 1.0
            else:
                matches = sum(1 for word in query_words if word in content)
                if matches == 0 or not query_words:
                    continue
                age_hours = max(0.0, (now - entry.timestamp).total_seconds() / 3600)
                score = (matches / len(query_words)) * max(0.5, 1.0 - age_hours / 24.0)
            scored.append((score * 1.2, entry))
        scored.sort(key=lambda item: (item[0], item[1].timestamp), reverse=True)
        return [entry for _, entry in scored[: max(0, limit)]]

    def build_context(self, query: str, max_tokens: int, project_key: str) -> str:
        relevant = self.retrieve_long_term(query, 10, project_key)
        lines: list[str] = []
        used = 0
        for entry in relevant:
            if used + entry.token_count > max_tokens:
                break
            lines.append(f"- [{entry.type.value}] {entry.content}")
            used += entry.token_count
        return "## 相关长期记忆\n\n" + "\n".join(lines) if lines else ""


class MemoryManager:
    MAX_TOOL_RESULT_CHARS = 500

    def __init__(
        self,
        client: LlmClient,
        project_root: Path,
        *,
        long_term: LongTermMemory | None = None,
        user_config_dir: Path | None = None,
    ) -> None:
        self.client = client
        self.project_root = project_root.resolve()
        self.project_key = str(self.project_root)
        self.context_profile = ContextProfile.from_window(getattr(client, "max_context_window", 128_000))
        self.short_term = ConversationMemory(self.context_profile.short_term_memory_budget)
        self.long_term = long_term or LongTermMemory()
        self.retriever = MemoryRetriever(self.long_term)
        self.project_loader = ProjectMemoryLoader(self.project_root, user_config_dir)
        self.context_compressor = ContextCompressor(client)
        self.history_compactor = ConversationHistoryCompactor(client)

    def add_user_message(self, content: str) -> None:
        self._add_short_term("user", content, MemoryType.CONVERSATION)

    def add_assistant_message(self, content: str) -> None:
        self._add_short_term("assistant", content, MemoryType.CONVERSATION)

    def add_tool_result(self, tool_name: str, result: str) -> None:
        truncated = (
            result[: self.MAX_TOOL_RESULT_CHARS] + "...(已截断)"
            if len(result) > self.MAX_TOOL_RESULT_CHARS
            else result
        )
        self.short_term.store(
            MemoryEntry(
                id=f"tool-{uuid.uuid4().hex[:8]}",
                content=f"[{tool_name}] {truncated}",
                type=MemoryType.TOOL_RESULT,
                metadata={"source": "tool", "toolName": tool_name},
            )
        )

    def store_fact(self, fact: str, scope: str = "project") -> MemoryEntry:
        normalized = "global" if scope.strip().lower() == "global" else "project"
        metadata = {"source": "fact", "scope": normalized}
        if normalized == "project":
            metadata["project"] = self.project_key
        entry = MemoryEntry(
            id=f"fact-{uuid.uuid4().hex[:8]}", content=fact.strip(), type=MemoryType.FACT, metadata=metadata
        )
        self.long_term.store(entry)
        return entry

    def prompt_context(self, query: str) -> str:
        parts = [
            self.project_loader.load_for_prompt(),
            self.retriever.build_context(query, self.context_profile.memory_context_tokens, self.project_key),
        ]
        return "\n\n".join(part for part in parts if part)

    async def compact_short_term_if_needed(self) -> bool:
        limit = min(self.short_term.max_tokens, self.context_profile.max_context_window - 3_300)
        if self.short_term.token_count < limit * self.context_profile.compression_trigger_ratio:
            return False
        return await self.context_compressor.compress(self.short_term) is not None

    async def compact_history_if_needed(self, history: list[Message]) -> bool:
        return await self.history_compactor.compact_if_needed(
            history, self.context_profile.compression_trigger_tokens
        )

    async def compact_history_now(self, history: list[Message]) -> bool:
        return await self.history_compactor.compact_now(history)

    def clear_short_term(self) -> None:
        self.short_term.clear()

    def status(self) -> str:
        return (
            f"短期记忆: {len(self.short_term.get_all())}条 / {self.short_term.token_count} tokens\n"
            f"长期记忆: {len(self.long_term.get_all())}条 / {self.long_term.token_count} tokens\n"
            f"上下文窗口: {self.context_profile.max_context_window} / "
            f"压缩阈值: {self.context_profile.compression_trigger_tokens} tokens"
        )

    def _add_short_term(self, source: str, content: str, memory_type: MemoryType) -> None:
        self.short_term.store(
            MemoryEntry(
                id=f"{source}-{uuid.uuid4().hex[:8]}",
                content=content,
                type=memory_type,
                metadata={"source": source},
            )
        )
