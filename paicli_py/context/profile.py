"""Context profile — derived from LLM context window size.

Mirrors ``com.paicli.context.ContextProfile``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from paicli_py.llm.client import LlmClient


# Global constants (matching Java)
MAX_SUMMARY_OUTPUT_RESERVE_TOKENS: int = 20_000
AUTOCOMPACT_BUFFER_TOKENS: int = 13_000
MIN_COMPRESSION_TRIGGER_RATIO: float = 0.50
_MIN_WINDOW: int = 8_000
_MCP_RESOURCE_INDEX_MIN_WINDOW: int = 32_000


@dataclass(frozen=True)
class ContextProfile:
    """Context-window-derived budget parameters."""

    max_context_window: int
    agent_token_budget: int
    compression_trigger_ratio: float
    short_term_memory_budget: int
    memory_context_tokens: int
    mcp_resource_index_enabled: bool
    prompt_caching_supported: bool
    prompt_cache_mode: str

    @classmethod
    def from_llm_client(cls, llm_client: LlmClient | None) -> ContextProfile:
        """Derive profile from an *llm_client* (or sensible defaults)."""
        window = max(_MIN_WINDOW, llm_client.max_context_window if llm_client else 128_000)
        return cls(
            max_context_window=window,
            agent_token_budget=cls._agent_budget(window),
            compression_trigger_ratio=cls._compression_trigger_ratio(window),
            short_term_memory_budget=cls._short_term_budget(window),
            memory_context_tokens=cls._memory_context_tokens(window),
            mcp_resource_index_enabled=window >= _MCP_RESOURCE_INDEX_MIN_WINDOW,
            prompt_caching_supported=llm_client.supports_prompt_caching if llm_client else False,
            prompt_cache_mode=llm_client.prompt_cache_mode if llm_client else "none",
        )

    @classmethod
    def custom(cls, context_window: int, short_term_memory_budget: int) -> ContextProfile:
        """Create a custom profile."""
        window = max(_MIN_WINDOW, context_window)
        short_term = max(1, short_term_memory_budget)
        return cls(
            max_context_window=window,
            agent_token_budget=cls._agent_budget(window),
            compression_trigger_ratio=cls._compression_trigger_ratio(window),
            short_term_memory_budget=short_term,
            memory_context_tokens=cls._memory_context_tokens(window),
            mcp_resource_index_enabled=window >= _MCP_RESOURCE_INDEX_MIN_WINDOW,
            prompt_caching_supported=False,
            prompt_cache_mode="none",
        )

    @property
    def compression_trigger_tokens(self) -> int:
        """Absolute token threshold at which compression fires."""
        return ContextProfile._auto_compact_trigger_tokens(self.max_context_window)

    def summary(self) -> str:
        threshold_pct = int(self.compression_trigger_ratio * 100)
        return (
            f"window: {self.max_context_window}"
            f" | 压缩阈值: {threshold_pct}% ({self.compression_trigger_tokens} tokens)"
            f" | 短期记忆预算: {self.short_term_memory_budget}"
            f" | MCP resource 索引: {'on' if self.mcp_resource_index_enabled else 'off'}"
            f" | prompt cache: {self.prompt_cache_mode}"
        )

    # ---- static helpers -------------------------------------------------

    @staticmethod
    def _agent_budget(window: int) -> int:
        return max(4_000, int(window * 0.8))

    @staticmethod
    def _short_term_budget(window: int) -> int:
        return max(4_000, int(window * 0.45))

    @staticmethod
    def _memory_context_tokens(window: int) -> int:
        return max(500, min(5_000, window // 200))

    @staticmethod
    def _compression_trigger_ratio(window: int) -> float:
        trigger = ContextProfile._auto_compact_trigger_tokens(window)
        return max(MIN_COMPRESSION_TRIGGER_RATIO, min(0.99, trigger / window))

    @staticmethod
    def _auto_compact_trigger_tokens(window: int) -> int:
        safe = max(_MIN_WINDOW, window)
        summary_reserve = min(MAX_SUMMARY_OUTPUT_RESERVE_TOKENS, max(1_000, safe // 4))
        buffer = min(AUTOCOMPACT_BUFFER_TOKENS, max(1_000, safe // 8))
        trigger = safe - summary_reserve - buffer
        return max(1_000, min(safe - 1, trigger))
