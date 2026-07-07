"""短期对话记忆 —— 有界 FIFO + 自动淘汰 + 压缩摘要。

对应 ``com.paicli.memory.ConversationMemory``。
"""

from __future__ import annotations

from collections import OrderedDict

from suncli_py.memory.memory_entry import MemoryEntry
from suncli_py.memory.protocol import Memory
from suncli_py.memory.query_tokenizer import matches, tokenize


class ConversationMemory(Memory):
    """基于 OrderedDict 的有界短期记忆。

    超出 token 预算时自动淘汰最旧条目；
    被淘汰的条目保存到压缩摘要列表，供后续 LLM 摘要合并。
    """

    def __init__(self, max_tokens: int) -> None:
        if max_tokens <= 0:
            raise ValueError("max_tokens 必须为正整数")
        self._entries: OrderedDict[str, MemoryEntry] = OrderedDict()
        self._max_tokens = max_tokens
        self._current_tokens = 0
        self._compressed_summaries: list[MemoryEntry] = []

    # ── Memory 协议实现 ──────────────────────────────────────

    def store(self, entry: MemoryEntry) -> None:
        self._entries[entry.id] = entry
        self._current_tokens += entry.token_count

        # 超出预算时自动淘汰最旧条目
        while self._current_tokens > self._max_tokens and len(self._entries) > 1:
            self._evict_oldest()

    def retrieve(self, entry_id: str) -> MemoryEntry | None:
        return self._entries.get(entry_id)

    def search(self, query: str, limit: int) -> list[MemoryEntry]:
        tokens = tokenize(query)
        result: list[MemoryEntry] = []
        for entry in self._entries.values():
            if matches(entry.content, tokens):
                result.append(entry)
                if len(result) >= limit:
                    break
        return result

    def get_all(self) -> list[MemoryEntry]:
        return list(self._entries.values())

    def delete(self, entry_id: str) -> bool:
        removed = self._entries.pop(entry_id, None)
        if removed:
            self._current_tokens -= removed.token_count
            return True
        return False

    def clear(self) -> None:
        self._entries.clear()
        self._current_tokens = 0
        self._compressed_summaries.clear()

    @property
    def token_count(self) -> int:
        return self._current_tokens

    def size(self) -> int:
        return len(self._entries)

    # ── 预算与压缩 ──────────────────────────────────────────

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    def set_max_tokens(self, max_tokens: int) -> None:
        if max_tokens <= 0:
            raise ValueError("max_tokens 必须为正整数")
        self._max_tokens = max_tokens
        while self._current_tokens > self._max_tokens and len(self._entries) > 1:
            self._evict_oldest()

    @property
    def compressed_summaries(self) -> list[MemoryEntry]:
        """获取被淘汰的旧记忆摘要（只读副本）。"""
        return list(self._compressed_summaries)

    def inject_summary(self, summary: MemoryEntry) -> None:
        """将压缩摘要回注到记忆中（替换旧的淘汰摘要列表）。"""
        self._compressed_summaries.clear()
        self._entries[summary.id] = summary
        self._current_tokens += summary.token_count

    @property
    def usage_ratio(self) -> float:
        return self._current_tokens / self._max_tokens if self._max_tokens > 0 else 0.0

    def get_status_summary(self) -> str:
        pct = int(self.usage_ratio * 100)
        return (
            f"短期记忆: {len(self._entries)}条 / {self._current_tokens} tokens"
            f" (预算: {self._max_tokens}, 使用率: {pct}%, 已压缩: {len(self._compressed_summaries)}条)"
        )

    # ── 内部 ────────────────────────────────────────────────

    def _evict_oldest(self) -> None:
        """淘汰最旧的一条记忆。"""
        if not self._entries:
            return
        _, oldest = self._entries.popitem(last=False)
        self._current_tokens -= oldest.token_count
        self._compressed_summaries.append(oldest)
