"""GLM (Zhipu) LLM provider.

Mirrors ``com.paicli.llm.GLMClient``.
"""

from __future__ import annotations

from paicli_py.llm.base import AbstractOpenAiCompatibleClient
from paicli_py.llm.models import ContentPart

CODING_API_URL = "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions"
MULTIMODAL_API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
DEFAULT_MODEL = "glm-5.1"


class GLMClient(AbstractOpenAiCompatibleClient):
    """ChatGLM client via Zhipu BigModel API."""

    def __init__(self, api_key: str, model: str | None = None, api_url: str | None = None) -> None:
        self._api_key = api_key
        self._model = model or DEFAULT_MODEL
        self._api_url = api_url or self._select_api_url(self._model)

    def _get_api_url(self) -> str:
        return self._api_url

    def _get_model(self) -> str:
        return self._model

    def _get_api_key(self) -> str:
        return self._api_key

    @property
    def max_context_window(self) -> int:
        return 200_000

    @property
    def supports_prompt_caching(self) -> bool:
        return True

    @property
    def prompt_cache_mode(self) -> str:
        return "glm-prompt-cache"

    def _to_image_url(self, part: ContentPart) -> str | None:
        if self._is_glm5v() and part.type == "image_base64":
            return part.image_base64
        return super()._to_image_url(part)

    @staticmethod
    def _select_api_url(model: str) -> str:
        if model.strip().lower().startswith("glm-5v"):
            return MULTIMODAL_API_URL
        return CODING_API_URL

    def _is_glm5v(self) -> bool:
        return self._model.strip().lower().startswith("glm-5v")
