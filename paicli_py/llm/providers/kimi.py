"""Kimi (Moonshot AI) LLM 提供商。

对应 ``com.paicli.llm.KimiClient``。
"""

from __future__ import annotations

from paicli_py.llm.base import AbstractOpenAiCompatibleClient

DEFAULT_MODEL = "kimi-k2-thinking-turbo"
DEFAULT_API_URL = "https://api.moonshot.cn/v1/chat/completions"


class KimiClient(AbstractOpenAiCompatibleClient):
    """Kimi API 客户端。"""

    def __init__(self, api_key: str, model: str | None = None, base_url: str | None = None) -> None:
        self._api_key = api_key
        self._model = model or DEFAULT_MODEL
        self._api_url = base_url or DEFAULT_API_URL

    def _get_api_url(self) -> str:
        return self._api_url

    def _get_model(self) -> str:
        return self._model

    def _get_api_key(self) -> str:
        return self._api_key

    @property
    def provider_name(self) -> str:
        return "kimi"

    @property
    def max_context_window(self) -> int:
        return 128_000
