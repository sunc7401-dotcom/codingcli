"""LLM client factory.

Mirrors ``com.paicli.llm.LlmClientFactory``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from suncli_py.llm.client import LlmClient

if TYPE_CHECKING:
    from suncli_py.config.config import PaiCliConfig


# Priority order when iterating providers
_PROVIDER_PRIORITY = ["glm", "deepseek", "step", "kimi", "freellmapi", "xfyun", "agnes"]


def normalize_provider(provider: str) -> str:
    """Normalize user-facing provider names to canonical keys."""
    normalized = provider.strip().lower()
    aliases: dict[str, str] = {
        "stepfun": "step",
        "step-fun": "step",
        "moonshot": "kimi",
        "moonshotai": "kimi",
        "moonshot-ai": "kimi",
        "free-llm-api": "freellmapi",
        "free_llm_api": "freellmapi",
        "freellm": "freellmapi",
        "free-llm": "freellmapi",
        "xfyun-maas": "xfyun",
        "xfyun_maas": "xfyun",
        "iflytek": "xfyun",
        "iflytek-maas": "xfyun",
        "iflytek_maas": "xfyun",
        "maas": "xfyun",
        "agnes-ai": "agnes",
        "agnes_ai": "agnes",
        "sapiens": "agnes",
        "sapiens-ai": "agnes",
        "sapiens_ai": "agnes",
    }
    return aliases.get(normalized, normalized)


def _first_configured(primary: str | None, fallback: str | None) -> str | None:
    if primary:
        return primary
    return fallback


def create_client(provider: str, config: PaiCliConfig) -> LlmClient | None:
    """Create an LlmClient for *provider* using *config*.

    Returns ``None`` if no API key can be resolved.
    """
    if not provider:
        return None

    normalized = normalize_provider(provider)
    configured_provider = provider.strip().lower()

    api_key = config.get_api_key(normalized)
    if (not api_key) and configured_provider != normalized:
        api_key = config.get_api_key(configured_provider)
    if not api_key:
        return None

    model = _first_configured(
        config.get_model(normalized),
        config.get_model(configured_provider) if configured_provider != normalized else None,
    )
    base_url = _first_configured(
        config.get_base_url(normalized),
        config.get_base_url(configured_provider) if configured_provider != normalized else None,
    )
    lora_id = _first_configured(
        config.get_lora_id(normalized),
        config.get_lora_id(configured_provider) if configured_provider != normalized else None,
    )

    # Lazy imports to avoid circular deps
    match normalized:
        case "glm":
            from suncli_py.llm.providers.glm import GLMClient
            return GLMClient(api_key=api_key, model=model)
        case "deepseek":
            from suncli_py.llm.providers.deepseek import DeepSeekClient
            return DeepSeekClient(api_key=api_key, model=model)
        case "step":
            from suncli_py.llm.providers.step import StepClient
            return StepClient(api_key=api_key, model=model, base_url=base_url)
        case "kimi":
            from suncli_py.llm.providers.kimi import KimiClient
            return KimiClient(api_key=api_key, model=model, base_url=base_url)
        case "freellmapi":
            from suncli_py.llm.providers.free_llm_api import FreeLlmApiClient
            return FreeLlmApiClient(api_key=api_key, model=model, base_url=base_url)
        case "xfyun":
            from suncli_py.llm.providers.xfyun_maas import XfyunMaaSClient
            return XfyunMaaSClient(api_key=api_key, model=model, base_url=base_url, lora_id=lora_id)
        case "agnes":
            from suncli_py.llm.providers.agnes import AgnesClient
            return AgnesClient(api_key=api_key, model=model, base_url=base_url)
        case _:
            return None


def create_client_from_config(config: PaiCliConfig) -> LlmClient | None:
    """Try the default provider first, then fall back through known providers."""
    client = create_client(config.default_provider, config)
    if client:
        return client

    for provider in _PROVIDER_PRIORITY:
        client = create_client(provider, config)
        if client:
            return client

    return None
