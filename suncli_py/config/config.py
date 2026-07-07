"""PaiCLI configuration management.

Mirrors ``com.paicli.config.PaiCliConfig``.
Loads from ``~/.paicli/config.json`` and falls back to environment variables
and ``.env`` files (both project-local and home directory).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, Field


class ProviderConfig(BaseModel):
    """Per-provider configuration."""

    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    lora_id: str | None = None
    temperature: float = 0.7
    max_tokens: int = 8192


class PaiCliConfig(BaseModel):
    """Root configuration persisted to ``~/.paicli/config.json``."""

    CONFIG_DIR: ClassVar[Path] = Path.home() / ".paicli"
    CONFIG_FILE: ClassVar[Path] = CONFIG_DIR / "config.json"

    default_provider: str = "glm"
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    @classmethod
    def load(cls) -> PaiCliConfig:
        """Load config from disk, falling back to defaults on error."""
        if cls.CONFIG_FILE.exists():
            try:
                return cls.model_validate_json(cls.CONFIG_FILE.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"⚠️ 配置文件读取失败，使用默认配置: {e}")
        return cls()

    def save(self) -> None:
        """Persist config to ``~/.paicli/config.json``."""
        self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        try:
            self.CONFIG_FILE.write_text(
                self.model_dump_json(indent=2, exclude_none=True),
                encoding="utf-8",
            )
        except Exception as e:
            print(f"⚠️ 配置保存失败: {e}")

    # ------------------------------------------------------------------
    # Resolved accessors (config → env → .env → fallback)
    # ------------------------------------------------------------------

    def get_api_key(self, provider: str) -> str | None:
        """Resolve API key for *provider*."""
        pc = self.providers.get(provider)
        if pc and pc.api_key:
            return pc.api_key
        return self._load_from_env(provider, "_API_KEY")

    def get_model(self, provider: str) -> str | None:
        """Resolve model name for *provider*."""
        pc = self.providers.get(provider)
        if pc and pc.model:
            return pc.model
        return self._load_from_env(provider, "_MODEL")

    def get_base_url(self, provider: str) -> str | None:
        """Resolve base URL for *provider*."""
        pc = self.providers.get(provider)
        if pc and pc.base_url:
            return pc.base_url
        return self._load_from_env(provider, "_BASE_URL")

    def get_lora_id(self, provider: str) -> str | None:
        """Resolve LoRA id (Xfyun only)."""
        pc = self.providers.get(provider)
        if pc and pc.lora_id:
            return pc.lora_id
        if provider.lower() != "xfyun":
            return None
        return self._load_from_env(provider, "_LORA_ID")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _env_key(provider: str, suffix: str) -> str:
        """Map provider name to environment variable key."""
        mapping: dict[str, str] = {
            "glm": "GLM",
            "deepseek": "DEEPSEEK",
            "step": "STEP",
            "kimi": "KIMI",
            "freellmapi": "FREELLMAPI",
            "xfyun": "XFYUN_MAAS",
        }
        base = mapping.get(provider.lower(), provider.upper())
        return base + suffix

    @classmethod
    def _load_from_env(cls, provider: str, suffix: str) -> str | None:
        """Try env var → .env files, with provider-specific fallbacks."""
        key = cls._env_key(provider, suffix)
        value = cls._read_env_or_dotenv(key)
        if value:
            return value

        # Kimi / Moonshot fallback
        if provider.lower() == "kimi":
            fallback = cls._read_env_or_dotenv("MOONSHOT" + suffix)
            if fallback:
                return fallback

        # Xfyun fallback
        if provider.lower() == "xfyun":
            fallback = cls._read_env_or_dotenv("XFYUN" + suffix)
            if fallback:
                return fallback

        return None

    @staticmethod
    def _read_env_or_dotenv(key: str) -> str | None:
        """Check os.environ first, then .env files."""
        value = os.environ.get(key)
        if value:
            return value.strip()
        return PaiCliConfig._read_from_dotenv(key)

    @staticmethod
    def _read_from_dotenv(key: str) -> str | None:
        """Parse ``key=value`` from ``.env`` (cwd) and ``~/.env``."""
        env_files = [Path(".env"), Path.home() / ".env"]
        for env_file in env_files:
            if not env_file.is_file():
                continue
            try:
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith(key + "="):
                        return line[len(key) + 1 :].strip()
            except OSError:
                continue
        return None
