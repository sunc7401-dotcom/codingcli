"""Token 预算追踪器。

对应 ``com.paicli.memory.TokenBudget``。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from paicli_py.memory.conversation import ConversationMemory


class TokenBudget:
    """跟踪上下文窗口的 token 使用情况，判断是否需要压缩。"""

    def __init__(self, max_context_window: int) -> None:
        self.max_context_window = max_context_window
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.cached_input_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def record_usage(self, input_tokens: int = 0, output_tokens: int = 0, cached_input_tokens: int = 0) -> None:
        """记录一次 LLM 调用的 token 消耗。"""
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cached_input_tokens += cached_input_tokens

    def needs_compression(self, memory: ConversationMemory, trigger_ratio: float) -> bool:
        """检查短期记忆占用率是否达到压缩阈值。

        比较的是 *短期记忆当前 token 数占上下文窗口的比例*，
        而非 (短期记忆 / 短期记忆预算) 的比例——后者会在重置预算后导致
        永远无法触发压缩。
        """
        if self.max_context_window <= 0:
            return False
        ratio = memory.token_count / self.max_context_window
        return ratio >= trigger_ratio

    def usage_ratio(self) -> float:
        if self.max_context_window <= 0:
            return 0.0
        return self.total_tokens / self.max_context_window

    def get_usage_report(self) -> str:
        pct = int(self.usage_ratio() * 100)
        return (
            f"Token 使用: {self.total_tokens}/{self.max_context_window} ({pct}%)"
            f" | 输入: {self.input_tokens} 输出: {self.output_tokens}"
            f" | 缓存命中: {self.cached_input_tokens}"
        )

    @staticmethod
    def estimate_messages_tokens(messages: list) -> int:
        """估算消息列表的总 token 数。

        中文约 1.5 字符/token，英文约 4 字符/token。
        """
        if not messages:
            return 0
        total = 0
        for m in messages:
            content = getattr(m, 'content', '') or ''
            total += max(1, len(content) // 2)
        return total
