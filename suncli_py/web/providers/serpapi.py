"""SerpAPI 搜索提供商 —— 对齐 Java SerpApiSearchProvider。

对应 ``com.paicli.web.SerpApiSearchProvider``。
"""

from __future__ import annotations

import httpx

from suncli_py.web.search_provider import SearchProvider, SearchResult


class SerpApiSearchProvider(SearchProvider):
    """SerpAPI 搜索服务。"""

    BASE_URL = "https://serpapi.com/search"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    @property
    def name(self) -> str:
        return "serpapi"

    def is_ready(self) -> bool:
        return bool(self._api_key)

    def unavailable_hint(self) -> str:
        return "SerpAPI 搜索不可用：请设置 SERPAPI_KEY"

    async def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        params = {
            "q": query,
            "api_key": self._api_key,
            "engine": "google",
            "num": str(min(top_k, 10)),
            "hl": "zh-cn",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(self.BASE_URL, params=params)
            if resp.status_code == 401:
                return []
            resp.raise_for_status()
            data = resp.json()

        results: list[SearchResult] = []
        position = 1

        organic = data.get("organic_results", [])
        for item in organic[:top_k]:
            results.append(SearchResult(
                position=position,
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=item.get("snippet", ""),
                source="serpapi",
            ))
            position += 1

        # 答案框/精选摘要作为降级方案
        if not results:
            answer_box = data.get("answer_box", {})
            if answer_box:
                snippet = answer_box.get("snippet") or answer_box.get("answer") or ""
                if snippet:
                    results.append(SearchResult(
                        position=1,
                        title=answer_box.get("title", "精选摘要"),
                        url=answer_box.get("link", ""),
                        snippet=snippet,
                        source="serpapi",
                    ))

        return results
