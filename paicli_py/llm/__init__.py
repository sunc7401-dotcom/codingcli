"""LLM 客户端层 —— LLM 提供商封装。

提供与各 LLM 提供商通信的异步客户端。
所有客户端均通过 OpenAI 兼容的 chat/completions 端点进行 SSE 流式调用。
"""

from paicli_py.llm.base import AbstractOpenAiCompatibleClient
from paicli_py.llm.client import LlmClient
from paicli_py.llm.factory import create_client, create_client_from_config, normalize_provider
from paicli_py.llm.trace import LlmTraceLogger

__all__ = [
    "LlmClient",
    "AbstractOpenAiCompatibleClient",
    "create_client",
    "create_client_from_config",
    "normalize_provider",
    "LlmTraceLogger",
]
