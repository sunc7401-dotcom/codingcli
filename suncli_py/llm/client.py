"""LLM client protocol.

Mirrors ``com.paicli.llm.LlmClient`` interface.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from suncli_py.llm.models import ChatResponse, Message, StreamListener


@runtime_checkable
class LlmClient(Protocol):
    """Async protocol for an LLM provider client."""

    async def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        listener: StreamListener | None = None,
    ) -> ChatResponse:
        """Send a chat request and return the full response.

        If *listener* is provided, streaming deltas are forwarded to it.
        """
        ...

    @property
    def model_name(self) -> str: ...

    @property
    def provider_name(self) -> str: ...

    @property
    def max_context_window(self) -> int:
        """Default 128k, overridden by providers."""
        return 128_000

    @property
    def supports_prompt_caching(self) -> bool:
        return False

    @property
    def supports_tools(self) -> bool:
        return True

    @property
    def supports_image_input(self) -> bool:
        return True

    @property
    def prompt_cache_mode(self) -> str:
        return "none"
