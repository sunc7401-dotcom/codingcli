"""智谱 AI 搜索提供商 —— 对齐 Java ZhipuSearchProvider。

对应 ``com.paicli.web.ZhipuSearchProvider``。

使用智谱 Web Search API: POST https://open.bigmodel.cn/api/paas/v4/web_search
"""

from __future__ import annotations

import httpx

from suncli_py.web.search_provider import SearchProvider, SearchResult

API_URL = "https://open.bigmodel.cn/api/paas/v4/web_search"
ALLOWED_ENGINES = {"search_std", "search_pro", "search_pro_sogou", "search_pro_quark"}


class ZhipuSearchProvider(SearchProvider):
    """智谱 AI Web 搜索 API。"""

    def __init__(self, api_key: str, engine: str = "search_std") -> None:
        self._api_key = api_key
        self._engine = engine if engine in ALLOWED_ENGINES else "search_std"

    @property
    def name(self) -> str:
        return "zhipu"

    def is_ready(self) -> bool:
        return bool(self._api_key)

    def unavailable_hint(self) -> str:
        return "Zhipu 搜索不可用：请设置 GLM_API_KEY"

    async def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        body = {
            "search_engine": self._engine,
            "search_query": query,
            "count": min(top_k, 50),
            "content_size": "medium",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(API_URL, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        results: list[SearchResult] = []
        for i, item in enumerate(data.get("results", data.get("data", [])), 1):
            results.append(SearchResult(
                position=i,
                title=item.get("title", ""),
                url=item.get("link", item.get("url", "")),
                snippet=item.get("content", item.get("snippet", "")),
                source="zhipu",
            ))
        return results[:top_k]
