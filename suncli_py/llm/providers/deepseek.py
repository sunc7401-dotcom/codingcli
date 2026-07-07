"""DeepSeek LLM 提供商。

对应 ``com.paicli.llm.DeepSeekClient``。
DeepSeek 不支持图片输入，且推荐使用 HTTP/1.1 协议以避免服务端 chunked-encoding 问题。
"""

from __future__ import annotations

from suncli_py.llm.base import AbstractOpenAiCompatibleClient

API_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-v4-flash"


class DeepSeekClient(AbstractOpenAiCompatibleClient):
    """DeepSeek API 客户端。

    DeepSeek 上下文窗口高达 100 万 token，支持自动前缀缓存。
    不支持图片输入（supports_image_input = False）。
    """

    def __init__(self, api_key: str, model: str | None = None, api_url: str | None = None) -> None:
        self._api_key = api_key
        self._model = model or DEFAULT_MODEL
        self._api_url = api_url or API_URL

    def _get_api_url(self) -> str:
        return self._api_url

    def _get_model(self) -> str:
        return self._model

    def _get_api_key(self) -> str:
        return self._api_key

    def _should_send_reasoning_in_history(self) -> bool:
        """DeepSeek 需要在历史消息中保留 reasoning_content 才能正确续写。"""
        return True

    @property
    def provider_name(self) -> str:
        return "deepseek"

    @property
    def max_context_window(self) -> int:
        return 1_000_000

    @property
    def supports_prompt_caching(self) -> bool:
        return True

    @property
    def supports_image_input(self) -> bool:
        return False

    @property
    def prompt_cache_mode(self) -> str:
        return "automatic-prefix-cache"
