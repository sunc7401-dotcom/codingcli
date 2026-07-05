"""讯飞星火 MaaS LLM 提供商。

对应 ``com.paicli.llm.XfyunMaaSClient``。
支持 LoRA 微调模型 ID。
"""

from __future__ import annotations

from paicli_py.llm.base import AbstractOpenAiCompatibleClient

DEFAULT_MODEL = "xdeepseek-v4-flash"


class XfyunMaaSClient(AbstractOpenAiCompatibleClient):
    """讯飞星火 MaaS API 客户端。"""

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        base_url: str | None = None,
        lora_id: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model or DEFAULT_MODEL
        self._api_url = base_url or "https://maas.cn-huadong-1.xf-yun.com/v1/chat/completions"
        self._lora_id = lora_id

    def _get_api_url(self) -> str:
        return self._api_url

    def _get_model(self) -> str:
        return self._model

    def _get_api_key(self) -> str:
        return self._api_key

    @property
    def provider_name(self) -> str:
        return "xfyun"

    @property
    def max_context_window(self) -> int:
        return 128_000

    def _customize_body(self, body: dict) -> None:
        """注入 LoRA ID 到请求体。"""
        if self._lora_id:
            body["lora_id"] = self._lora_id
