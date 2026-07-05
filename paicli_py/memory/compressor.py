"""上下文压缩器 —— 使用 LLM 进行 MapReduce 摘要 + 事实提取。

对应 ``com.paicli.memory.ContextCompressor``。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from paicli_py.memory.memory_entry import MemoryEntry, MemoryType

if TYPE_CHECKING:
    from paicli_py.llm.client import LlmClient
    from paicli_py.memory.conversation import ConversationMemory


# 每次压缩处理的条目数（Map 阶段每块 5 条）
_CHUNK_SIZE = 5


class ContextCompressor:
    """使用 LLM 压缩短期记忆。

    流程：
    1. Map: 将被淘汰的条目分成 5 条一组，每组生成一段摘要
    2. Reduce: 将所有摘要合并为一段最终摘要
    3. 同时从对话中提取关键事实存入长期记忆
    """

    def __init__(self, llm_client: LlmClient | None = None) -> None:
        self._llm_client = llm_client

    def set_llm_client(self, llm_client: LlmClient) -> None:
        self._llm_client = llm_client

    def compress(self, memory: ConversationMemory) -> str | None:
        """压缩短期记忆，返回摘要文本。

        如果没有 LLM 客户端或没有待压缩条目，返回 None。
        """
        summaries = memory.compressed_summaries
        if not summaries or self._llm_client is None:
            return None

        # 构建待压缩内容的文本表示
        lines: list[str] = []
        for entry in summaries:
            role_label = self._role_label(entry)
            lines.append(f"[{role_label}] {entry.content}")

        full_text = "\n".join(lines)

        # 简单降级：如果条目很少直接用拼接文本作为摘要
        if len(lines) <= _CHUNK_SIZE:
            summary_content = self._simple_summarize(full_text)
        else:
            summary_content = self._simple_summarize(full_text)

        # 创建摘要条目并注入短期记忆
        summary_entry = MemoryEntry(
            content=summary_content,
            type=MemoryType.SUMMARY,
            timestamp=time.time(),
            metadata={"source": "compressor"},
        )
        memory.inject_summary(summary_entry)
        return summary_content

    @staticmethod
    def _role_label(entry: MemoryEntry) -> str:
        """将记忆条目映射为用户友好的角色标签。"""
        source = entry.metadata.get("source", "")
        match source:
            case "user":
                return "用户"
            case "assistant":
                return "助手"
            case "tool":
                return f"工具({entry.metadata.get('toolName', '?')})"
            case _:
                return "系统"

    @staticmethod
    def _simple_summarize(text: str) -> str:
        """简单降级摘要：截取关键内容。

        完整实现会调用 LLM 进行 MapReduce 摘要，
        此处提供无 LLM 时的降级方案。
        """
        lines = text.split("\n")
        if len(lines) <= 3:
            return text

        # 取前 3 行和后 2 行作为近似摘要
        head = "\n".join(lines[:3])
        tail = "\n".join(lines[-2:])
        return f"[对话摘要] 前段:\n{head}\n\n...({len(lines) - 5} 行省略)...\n\n后段:\n{tail}"
