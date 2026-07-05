"""Token 用量格式化工具。

对应 ``com.paicli.context.TokenUsageFormatter``。

按提供商计算人民币成本估算。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from paicli_py.llm.client import LlmClient


def format_tokens(count: int) -> str:
    """人类可读的 token 数量（如 1.2k, 3.5M）。"""
    if count < 1000:
        return str(count)
    if count < 1_000_000:
        return f"{count / 1000:.1f}k"
    return f"{count / 1_000_000:.1f}M"


def estimated_cost_cny(llm_client: LlmClient | None, input_tokens: int, output_tokens: int, cached_input_tokens: int = 0) -> str:
    """按提供商估算人民币成本。

    各提供商的百万 token 定价（CNY/百万）：
    - DeepSeek: 输入 2 / 输出 8
    - GLM / 其他: 输入 5 / 输出 20
    - DeepSeek 缓存命中: 0.5
    - GLM 缓存命中: 1
    """
    if llm_client is None:
        return "—"

    provider = llm_client.provider_name.lower()
    if provider == "deepseek":
        input_price = 2.0
        output_price = 8.0
        cached_price = 0.5
    else:
        input_price = 5.0
        output_price = 20.0
        cached_price = 1.0

    input_cost = (input_tokens / 1_000_000) * input_price
    output_cost = (output_tokens / 1_000_000) * output_price
    _cached_cost = (cached_input_tokens / 1_000_000) * cached_price
    total = input_cost + output_cost

    if total < 0.01:
        return f"≈¥{total:.4f}"
    if total < 1:
        return f"≈¥{total:.3f}"
    return f"≈¥{total:.2f}"


def format_usage(llm_client: LlmClient | None, input_tokens: int, output_tokens: int,
                 cached_input_tokens: int = 0, start_ns: int | None = None) -> str:
    """生成 token 用量摘要字符串。

    对应 Java TokenUsageFormatter.format()。
    """
    parts: list[str] = []
    parts.append(f"输入: {format_tokens(input_tokens)}")
    parts.append(f"输出: {format_tokens(output_tokens)}")
    total = input_tokens + output_tokens
    parts.append(f"合计: {format_tokens(total)}")

    if cached_input_tokens > 0:
        parts.append(f"缓存: {format_tokens(cached_input_tokens)}")

    cost = estimated_cost_cny(llm_client, input_tokens, output_tokens, cached_input_tokens)
    parts.append(f"费用: {cost}")

    if start_ns is not None:
        elapsed_ms = (time.monotonic_ns() - start_ns) / 1_000_000
        parts.append(_format_elapsed(elapsed_ms))

    return " | ".join(parts)


def _format_elapsed(ms: float) -> str:
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.1f}s"
