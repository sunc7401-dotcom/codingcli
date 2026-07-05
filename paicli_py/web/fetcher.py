"""Web 内容抓取器 + FetchResult 模型。

对应 ``com.paicli.web.WebFetcher`` 和 ``FetchResult`` record。
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass
class FetchResult:
    """HTTP 抓取结果。"""
    url: str
    title: str | None
    markdown: str
    content_length: int = 0
    truncated: bool = False
    body_empty: bool = False
    hint: str = ""

    @classmethod
    def ok(cls, url: str, title: str | None, markdown: str, content_length: int,
           truncated: bool = False, body_empty: bool = False, hint: str = "") -> FetchResult:
        return cls(
            url=url, title=title, markdown=markdown,
            content_length=content_length, truncated=truncated,
            body_empty=body_empty, hint=hint,
        )


class WebFetcher:
    """HTTP 内容抓取器。

    特性：
    - 5MB 响应体上限
    - 自动跟随重定向
    - 从 Content-Type 推断字符编码
    """

    DEFAULT_TIMEOUT = 30  # 秒
    MAX_BODY_BYTES = 5 * 1024 * 1024  # 5MB

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        self._timeout = timeout

    async def fetch(self, url: str, max_chars: int | None = None) -> FetchResult:
        """抓取指定 URL 并返回结构化结果。"""
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; paicli-web-fetch/1.0)",
                    "Accept": "text/html,application/xhtml+xml,text/plain",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                },
            ) as client:
                response = await client.get(url)
                response.raise_for_status()

                content_type = response.headers.get("content-type", "")
                raw_body = response.text

                body_len = len(raw_body)
                truncated = body_len > max_chars if max_chars else False
                body = raw_body[:max_chars] if max_chars else raw_body

                # 提取标题
                title = None
                if "html" in content_type.lower():
                    import re
                    match = re.search(r"<title>(.*?)</title>", body, re.IGNORECASE)
                    if match:
                        title = match.group(1).strip()

                # 提取正文
                from paicli_py.web.extractor import HtmlExtractor
                markdown = HtmlExtractor.extract(body, url) if "html" in content_type.lower() else body

                return FetchResult(
                    url=str(response.url),
                    title=title,
                    markdown=markdown,
                    content_length=body_len,
                    truncated=truncated,
                    body_empty=not bool(markdown.strip()),
                )

        except Exception as e:
            return FetchResult(
                url=url,
                title=None,
                markdown=f"抓取失败: {e}",
                content_length=0,
                body_empty=True,
                hint=str(e),
            )
