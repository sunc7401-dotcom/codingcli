"""嵌入客户端 —— Ollama + OpenAI 兼容 API。

对应 ``com.paicli.rag.EmbeddingClient``。

配置来源（环境变量）:
- EMBEDDING_PROVIDER: ollama | openai
- EMBEDDING_MODEL: 模型名
- EMBEDDING_BASE_URL: API 地址
- EMBEDDING_API_KEY: API Key
"""

from __future__ import annotations

import os

import httpx


class EmbeddingClient:
    """文本嵌入客户端。"""

    DEFAULT_OLLAMA_URL = "http://localhost:11434/api/embeddings"
    DEFAULT_OPENAI_URL = "https://api.openai.com/v1/embeddings"
    DEFAULT_MODEL = "nomic-embed-text:latest"

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._provider = provider or os.environ.get("EMBEDDING_PROVIDER", "ollama")
        self._model = model or os.environ.get("EMBEDDING_MODEL", self.DEFAULT_MODEL)
        self._base_url = base_url or os.environ.get("EMBEDDING_BASE_URL", "")
        self._api_key = api_key or os.environ.get("EMBEDDING_API_KEY", "")

    async def embed(self, text: str) -> list[float]:
        """获取单条文本的嵌入向量。"""
        return (await self.embed_batch([text]))[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量获取嵌入向量。

        每段文本截断到 2000 字符。
        """
        truncated = [t[:2000] for t in texts]

        if self._provider == "ollama":
            return await self._embed_ollama(truncated)
        else:
            return await self._embed_openai(truncated)

    async def _embed_ollama(self, texts: list[str]) -> list[list[float]]:
        url = self._base_url or self.DEFAULT_OLLAMA_URL
        embeddings: list[list[float]] = []

        async with httpx.AsyncClient(timeout=60) as client:
            for text in texts:
                resp = await client.post(url, json={"model": self._model, "prompt": text})
                resp.raise_for_status()
                data = resp.json()
                embeddings.append(data["embedding"])

        return embeddings

    async def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        url = self._base_url or self.DEFAULT_OPENAI_URL
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                url,
                json={"model": self._model, "input": texts},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        # 按索引保持顺序
        items = sorted(data["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in items]
