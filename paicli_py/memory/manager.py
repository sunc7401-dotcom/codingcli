"""记忆管理器 —— 记忆系统的门面类。

对应 ``com.paicli.memory.MemoryManager``。

统一管理短期记忆、长期记忆、上下文压缩和检索，
为 Agent 提供简洁的记忆存取接口。
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from paicli_py.context.profile import ContextProfile
from paicli_py.memory.compressor import ContextCompressor
from paicli_py.memory.conversation import ConversationMemory
from paicli_py.memory.history_compactor import ConversationHistoryCompactor
from paicli_py.memory.long_term import LongTermMemory
from paicli_py.memory.memory_entry import MemoryEntry, MemoryType
from paicli_py.memory.retriever import MemoryRetriever
from paicli_py.memory.token_budget import TokenBudget

if TYPE_CHECKING:
    from paicli_py.llm.client import LlmClient


# 工具结果在记忆中的最大字符数（完整结果已在消息历史里，记忆只保留摘要）
MAX_TOOL_RESULT_CHARS = 500


class MemoryManager:
    """记忆系统门面。

    使用示例::

        mm = MemoryManager(llm_client)
        mm.add_user_message("帮我写一个排序函数")
        mm.add_assistant_message("好的，这是快速排序的实现...")
        context = mm.build_context_for_query("优化排序", max_tokens=2000)
    """

    def __init__(
        self,
        llm_client: LlmClient | None = None,
        short_term_budget: int | None = None,
        context_window: int | None = None,
        long_term_memory: LongTermMemory | None = None,
    ) -> None:
        # 解析上下文策略
        if short_term_budget is not None and context_window is not None:
            self._context_profile = ContextProfile.custom(context_window, short_term_budget)
        elif llm_client is not None:
            self._context_profile = ContextProfile.from_llm_client(llm_client)
        else:
            self._context_profile = ContextProfile.custom(128_000, 57_600)

        self._short_term = ConversationMemory(self._context_profile.short_term_memory_budget)
        self._long_term = long_term_memory or LongTermMemory()
        self._compressor = ContextCompressor(llm_client)
        self._retriever = MemoryRetriever(self._short_term, self._long_term)
        self._token_budget = TokenBudget(self._context_profile.max_context_window)
        self._current_project = self._default_project_key()
        self._history_compactor = ConversationHistoryCompactor(self._compressor)

    # ── LLM 客户端 / 上下文策略更新 ─────────────────────────

    def set_llm_client(self, llm_client: LlmClient) -> None:
        """更新 LLM 客户端并重新计算上下文策略。"""
        self._compressor.set_llm_client(llm_client)
        self.apply_context_profile(ContextProfile.from_llm_client(llm_client))

    def apply_context_profile(self, profile: ContextProfile) -> None:
        """应用新的上下文策略。"""
        self._context_profile = profile
        self._token_budget = TokenBudget(profile.max_context_window)
        self._short_term.set_max_tokens(profile.short_term_memory_budget)

    def set_project_path(self, project_path: str | None) -> None:
        """设置当前项目路径（用于长期记忆的项目范围过滤）。"""
        if not project_path:
            return
        self._current_project = self._normalize_project_key(project_path)

    # ── 消息记录 ────────────────────────────────────────────

    def add_user_message(self, content: str) -> None:
        """添加用户消息到短期记忆。"""
        entry = MemoryEntry(
            id=f"user-{uuid.uuid4().hex[:8]}",
            content=content,
            type=MemoryType.CONVERSATION,
            timestamp=time.time(),
            metadata={"source": "user"},
            token_count=self._estimate_tokens(content),
        )
        self._short_term.store(entry)
        self._compress_if_needed()

    def add_assistant_message(self, content: str) -> None:
        """添加助手回复到短期记忆。"""
        entry = MemoryEntry(
            id=f"assistant-{uuid.uuid4().hex[:8]}",
            content=content,
            type=MemoryType.CONVERSATION,
            timestamp=time.time(),
            metadata={"source": "assistant"},
            token_count=self._estimate_tokens(content),
        )
        self._short_term.store(entry)
        self._compress_if_needed()

    def add_tool_result(self, tool_name: str, result: str) -> None:
        """添加工具执行结果到短期记忆（截断过长结果）。"""
        truncated = result if len(result) <= MAX_TOOL_RESULT_CHARS else result[:MAX_TOOL_RESULT_CHARS] + "...(已截断)"
        content = f"[{tool_name}] {truncated}"
        entry = MemoryEntry(
            id=f"tool-{uuid.uuid4().hex[:8]}",
            content=content,
            type=MemoryType.TOOL_RESULT,
            timestamp=time.time(),
            metadata={"source": "tool", "toolName": tool_name},
            token_count=self._estimate_tokens(content),
        )
        self._short_term.store(entry)
        self._compress_if_needed()

    # ── 长期记忆 ────────────────────────────────────────────

    def store_fact(self, fact: str, scope: str = "project") -> None:
        """存储关键事实到长期记忆。"""
        normalized_scope = self._normalize_scope(scope)
        metadata: dict[str, str] = {"source": "fact", "scope": normalized_scope}
        if normalized_scope != "global":
            metadata["project"] = self._current_project

        entry = MemoryEntry(
            id=f"fact-{uuid.uuid4().hex[:8]}",
            content=fact,
            type=MemoryType.FACT,
            timestamp=time.time(),
            metadata=metadata,
            token_count=self._estimate_tokens(fact),
        )
        self._long_term.store(entry)

    def retrieve_relevant(self, query: str, limit: int = 10) -> list[MemoryEntry]:
        """检索与查询最相关的记忆。"""
        return self._retriever.retrieve(query, limit)

    def list_long_term(self) -> list[MemoryEntry]:
        return self._long_term.get_all()

    def search_long_term(self, query: str, limit: int = 10) -> list[MemoryEntry]:
        return self._long_term.search(query, limit, self._current_project)

    def delete_long_term(self, entry_id: str) -> bool:
        return self._long_term.delete(entry_id)

    # ── 上下文构建 ──────────────────────────────────────────

    def build_context_for_query(self, query: str, max_tokens: int | None = None) -> str:
        """构建用于 LLM system prompt 的记忆上下文。"""
        limit = max_tokens or self._context_profile.memory_context_tokens
        return self._retriever.build_context_for_query(query, limit, self._current_project)

    # ── Token 追踪 ──────────────────────────────────────────

    def record_token_usage(self, input_tokens: int = 0, output_tokens: int = 0, cached_input_tokens: int = 0) -> None:
        """记录一次 LLM 调用的 token 消耗。"""
        self._token_budget.record_usage(input_tokens, output_tokens, cached_input_tokens)

    # ── 压缩 ────────────────────────────────────────────────

    def _compress_if_needed(self) -> bool:
        """检查并在必要时触发短期记忆压缩。"""
        if not self._token_budget.needs_compression(
            self._short_term, self._context_profile.compression_trigger_ratio
        ):
            return False

        before = self._short_term.token_count
        pct = int(self._context_profile.compression_trigger_ratio * 100)
        logger.info(f"上下文占用达到压缩阈值（{pct}%），触发短期记忆压缩")

        summary = self._compressor.compress(self._short_term)
        if summary:
            after = self._short_term.token_count
            preview = summary[:100]
            logger.info(f"短期记忆压缩完成: {before} -> {after} tokens, summaryPreview={preview}")
        return summary is not None

    def compact_history(self, messages: list, keep_recent: int = 10) -> list:
        """压缩 LLM 消息历史（委托给 ConversationHistoryCompactor）。"""
        return self._history_compactor.compact(messages, keep_recent)

    # ── 清空 ────────────────────────────────────────────────

    def clear_short_term(self) -> None:
        """清空短期记忆（保留长期记忆）。"""
        self._short_term.clear()

    def clear_long_term(self) -> None:
        """清空长期记忆。"""
        self._long_term.clear()

    # ── 状态查询 ────────────────────────────────────────────

    def get_system_status(self) -> str:
        """获取记忆系统整体状态。"""
        return "\n".join([
            f"上下文策略: {self._context_profile.summary()}",
            self._short_term.get_status_summary(),
            self._long_term.get_status_summary(),
            self._token_budget.get_usage_report(),
        ])

    # ── 属性 ────────────────────────────────────────────────

    @property
    def short_term_memory(self) -> ConversationMemory:
        return self._short_term

    @property
    def long_term_memory(self) -> LongTermMemory:
        return self._long_term

    @property
    def token_budget(self) -> TokenBudget:
        return self._token_budget

    @property
    def context_profile(self) -> ContextProfile:
        return self._context_profile

    @property
    def current_project(self) -> str:
        return self._current_project

    # ── 内部工具方法 ────────────────────────────────────────

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """粗略估算 token 数（中文 ≈1.5 字符/token, 英文 ≈4 字符/token）。"""
        if not text:
            return 0
        # 简单混合估算
        chinese_chars = sum(1 for c in text if "一" <= c <= "鿿")
        other_chars = len(text) - chinese_chars
        return max(1, int(chinese_chars / 1.5 + other_chars / 4))

    @staticmethod
    def _normalize_scope(scope: str | None) -> str:
        if not scope:
            return "project"
        return "global" if scope.strip().lower() == "global" else "project"

    @staticmethod
    def _default_project_key() -> str:
        return MemoryManager._normalize_project_key(str(Path.cwd()))

    @staticmethod
    def _normalize_project_key(path: str) -> str:
        try:
            p = Path(path).resolve()
            if p.exists():
                return str(p)
            return str(p)
        except Exception:
            return str(Path(path).absolute())
