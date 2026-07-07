"""Agnes (Sapiens) LLM 提供商。

对应 ``com.paicli.llm.AgnesClient``。
"""

from __future__ import annotations

from suncli_py.llm.base import AbstractOpenAiCompatibleClient

DEFAULT_MODEL = "agnes-4-pro-max"


class AgnesClient(AbstractOpenAiCompatibleClient):
    """Agnes API 客户端。"""

    def __init__(self, api_key: str, model: str | None = None, base_url: str | None = None) -> None:
        self._api_key = api_key
        self._model = model or DEFAULT_MODEL
        self._api_url = base_url or "https://api.agnes.ai/v1/chat/completions"

    def _get_api_url(self) -> str:
        return self._api_url

    def _get_model(self) -> str:
        return self._model

    def _get_api_key(self) -> str:
        return self._api_key

    @property
    def provider_name(self) -> str:
        return "agnes"
