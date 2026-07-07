"""HTML 正文提取器。

对应 ``com.paicli.web.HtmlExtractor``。
使用 trafilatura 作为主提取器，beautifulsoup4 作为降级方案。
"""

from __future__ import annotations


class HtmlExtractor:
    """从 HTML 中提取可读的 Markdown 正文。"""

    @staticmethod
    def extract(html: str, url: str = "") -> str:
        """提取正文内容。

        优先使用 trafilatura（质量更好），
        失败时降级为 beautifulsoup4 简单提取。
        """
        # 尝试 trafilatura
        try:
            import trafilatura
            result = trafilatura.extract(
                html,
                url=url,
                output_format="markdown",
                include_links=True,
                include_images=False,
            )
            if result and result.strip():
                return result.strip()
        except Exception:
            pass

        # 降级：beautifulsoup4 简单提取
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")

            # 移除脚本和样式
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()

            body = soup.find("body")
            text = body.get_text(separator="\n", strip=True) if body else soup.get_text(separator="\n", strip=True)

            # 压缩多余空行
            import re
            text = re.sub(r"\n{3,}", "\n\n", text)
            return text.strip()
        except Exception:
            pass

        return "(无法提取正文)"
