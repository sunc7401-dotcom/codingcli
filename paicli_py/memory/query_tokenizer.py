"""记忆查询分词器 —— 中文 + 英文混合分词。

对应 ``com.paicli.memory.MemoryQueryTokenizer``。
依赖 jieba 进行中文分词。
"""

from __future__ import annotations

import re

import jieba

# 英文单词 / 数字模式
_WORD_PATTERN = re.compile(r"[a-zA-Z0-9_]+")


def tokenize(query: str) -> set[str]:
    """将查询文本拆分为去重的 token 集合。

    中文使用 jieba 分词，英文和数字按空白/标点切分。
    """
    if not query:
        return set()

    tokens: set[str] = set()

    # jieba 中文分词
    for token in jieba.cut(query):
        token = token.strip()
        if token:
            tokens.add(token.lower())

    # 补充英文/数字 token
    for match in _WORD_PATTERN.finditer(query):
        tokens.add(match.group().lower())

    return tokens


def matches(content: str, query_tokens: set[str]) -> bool:
    """检查 *content* 是否匹配至少一个 *query_tokens*。"""
    if not query_tokens:
        return False
    content_lower = content.lower()
    return any(token in content_lower for token in query_tokens)
