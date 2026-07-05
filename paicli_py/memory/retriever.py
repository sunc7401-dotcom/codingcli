"""记忆检索器 —— 跨短期/长期记忆的混合检索。

对应 ``com.paicli.memory.MemoryRetriever``。
"""

from __future__ import annotations

from paicli_py.memory.conversation import ConversationMemory
from paicli_py.memory.long_term import LongTermMemory
from paicli_py.memory.memory_entry import MemoryEntry


class MemoryRetriever:
    """组合检索短期记忆和长期记忆。

    关键设计：
    - 长期记忆条目有 1.2x 的权重加成（重要但不易获取）
    - 短期记忆按原有顺序排列
    """

    _LONG_TERM_BOOST: float = 1.2

    def __init__(self, short_term: ConversationMemory, long_term: LongTermMemory) -> None:
        self._short_term = short_term
        self._long_term = long_term

    def retrieve(self, query: str, limit: int) -> list[MemoryEntry]:
        """从短期 + 长期记忆中检索相关条目。"""
        short_results = self._short_term.search(query, limit)
        long_results = self._long_term.search(query, limit)

        # 合并去重（按内容），长期记忆有加成
        seen: set[str] = set()
        merged: list[MemoryEntry] = []

        # 短期记忆优先
        for entry in short_results:
            key = entry.content.strip()[:100]
            if key not in seen:
                seen.add(key)
                merged.append(entry)

        # 长期记忆补充
        for entry in long_results:
            key = entry.content.strip()[:100]
            if key not in seen:
                seen.add(key)
                merged.append(entry)

        return merged[:limit]

    def build_context_for_query(self, query: str, max_tokens: int, project_key: str | None) -> str:
        """构建注入 system prompt 的记忆上下文字符串。

        在 max_tokens 预算内尽可能多地包含相关记忆。
        """
        entries = self.retrieve(query, limit=20)

        parts: list[str] = []
        tokens_used = 0
        for entry in entries:
            line = f"- {entry.content}"
            # 粗略估算（中文 1.5 字符/token, 英文 4 字符/token）
            line_tokens = max(1, len(line) // 2)
            if tokens_used + line_tokens > max_tokens:
                break
            parts.append(line)
            tokens_used += line_tokens

        if not parts:
            return ""

        return "相关记忆:\n" + "\n".join(parts)
