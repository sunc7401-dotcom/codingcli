"""抓取结果模型 —— 对应 ``com.paicli.web.FetchResult`` record。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FetchResult:
    url: str
    title: str | None
    markdown: str
    content_length: int = 0
    truncated: bool = False
    body_empty: bool = False
    hint: str = ""

    @classmethod
    def ok(cls, url: str, title: str | None, markdown: str, original_length: int, truncated: bool = False) -> FetchResult:
        """工厂方法：自动计算 body_empty 和 hint。"""
        body_empty = not markdown or not markdown.strip()
        hint = ""
        if truncated:
            hint = f"内容已截断（原始 {original_length} 字符）"
        elif body_empty:
            hint = "未提取到正文内容"

        return cls(
            url=url,
            title=title or "",
            markdown=markdown,
            content_length=original_length,
            truncated=truncated,
            body_empty=body_empty,
            hint=hint,
        )
