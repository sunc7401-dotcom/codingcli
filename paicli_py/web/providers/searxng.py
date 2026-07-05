"""SearXNG 搜索提供商 —— 对齐 Java SearxngSearchProvider。

对应 ``com.paicli.web.SearxngSearchProvider``。
"""

from __future__ import annotations

import httpx

from paicli_py.web.search_provider import SearchProvider, SearchResult


class SearxngSearchProvider(SearchProvider):
    """SearXNG 自建搜索实例。"""

    def __init__(self, base_url: str = "http://localhost:8080") -> None:
        self._base_url = base_url.rstrip("/")

    @property
    def name(self) -> str:
        return "searxng"

    def is_ready(self) -> bool:
        return bool(self._base_url)

    def unavailable_hint(self) -> str:
        return "SearXNG 搜索不可用：请设置 SEARXNG_URL"

    async def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        url = f"{self._base_url}/search"
        params = {"q": query, "format": "json", "language": "zh"}
        headers = {"User-Agent": "paicli-web-search/1.0"}

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        results: list[SearchResult] = []
        for i, item in enumerate(data.get("results", [])[:top_k], 1):
            results.append(SearchResult(
                position=i,
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", item.get("snippet", "")),
                source=f"searxng ({item.get('engine', '?')})",
            ))
        return results
