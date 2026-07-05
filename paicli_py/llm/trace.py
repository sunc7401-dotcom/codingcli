"""LLM request/response trace logging.

Mirrors ``com.paicli.llm.LlmTraceLogger``.
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger


class LlmTraceLogger:
    """Logs full LLM request/response pairs for debugging."""

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    def log_request(self, provider: str, model: str, body: dict[str, Any]) -> None:
        if not self.enabled:
            return
        # Redact message content for privacy
        safe = body.copy()
        if "messages" in safe:
            safe["messages"] = [
                {**m, "content": f"[{len(str(m.get('content', '')))} chars]"}
                for m in safe["messages"]
            ]
        logger.debug(f"[LLM TRACE] {provider}/{model} REQUEST: {json.dumps(safe, ensure_ascii=False)}")

    def log_response(self, provider: str, model: str, response: Any) -> None:
        if not self.enabled:
            return
        logger.debug(f"[LLM TRACE] {provider}/{model} RESPONSE tokens: {getattr(response, 'input_tokens', 0)}→{getattr(response, 'output_tokens', 0)}")

    def log_error(self, provider: str, model: str, error: Exception) -> None:
        if not self.enabled:
            return
        logger.warning(f"[LLM TRACE] {provider}/{model} ERROR: {error}")
