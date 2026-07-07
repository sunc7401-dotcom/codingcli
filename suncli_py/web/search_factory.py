"""搜索提供商工厂 —— 对齐 Java SearchProviderFactory。

对应 ``com.paicli.web.SearchProviderFactory``。

自动检测可用提供商: GLM_KEY > SERPAPI_KEY > SEARXNG_URL
"""

from __future__ import annotations

import os

from suncli_py.web.search_provider import SearchProvider


class SearchProviderFactory:
    """搜索提供商工厂。

    配置来源优先级: env var > .env 文件
    """

    @staticmethod
    def create() -> SearchProvider | None:
        """根据环境变量自动检测并创建搜索提供商。"""
        # 1. Zhipu (GLM)
        glm_key = _read_config("GLM_API_KEY")
        if glm_key:
            from suncli_py.web.providers.zhipu import ZhipuSearchProvider
            engine = os.environ.get("ZHIPU_SEARCH_ENGINE", "search_std")
            return ZhipuSearchProvider(glm_key, engine)

        # 2. SerpAPI
        serpapi_key = _read_config("SERPAPI_KEY")
        if serpapi_key:
            from suncli_py.web.providers.serpapi import SerpApiSearchProvider
            return SerpApiSearchProvider(serpapi_key)

        # 3. SearXNG
        searxng_url = _read_config("SEARXNG_URL")
        if searxng_url:
            from suncli_py.web.providers.searxng import SearxngSearchProvider
            return SearxngSearchProvider(searxng_url)

        return None


def _read_config(key: str) -> str | None:
    """读取配置: os.environ → .env 文件。"""
    value = os.environ.get(key, "")
    if value:
        return value.strip()

    # 检查 .env 文件
    for env_file in [".env", os.path.join(os.path.expanduser("~"), ".env")]:
        try:
            with open(env_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(key + "="):
                        return line[len(key) + 1:].strip().strip("\"'")
        except (FileNotFoundError, OSError):
            continue

    return None
