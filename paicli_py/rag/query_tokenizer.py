"""RAG 查询分词器 —— 对应 ``com.paicli.rag.RagQueryTokenizer``。"""

from __future__ import annotations

import re

ASCII_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_.$-]{2,}")

_STOP_WORDS = {"怎么", "如何", "什么", "哪里", "哪个", "为什么", "是不是", "能不能", "可以", "有没有", "是什么", "怎么做", "怎么样", "怎样"}


def tokenize(query: str) -> set[str]:
    """将自然语言 RAG 查询分解为去重 token 集合。"""
    if not query:
        return set()

    tokens: set[str] = set()

    # 1. jieba 中文分词
    try:
        import jieba
        for token in jieba.cut(query):
            token = token.strip()
            if _is_useful_token(token):
                tokens.add(token.lower())
    except ImportError:
        pass

    # 2. ASCII 标识符提取
    for match in ASCII_TOKEN.finditer(query):
        token = match.group()
        if _is_useful_token(token):
            tokens.add(token.lower())

    return tokens


def _is_useful_token(token: str) -> bool:
    """过滤无效 token。"""
    if len(token) < 2:
        return False
    if token in _STOP_WORDS:
        return False
    # 必须包含汉字或字母数字
    return any(c.isalpha() or '一' <= c <= '鿿' for c in token)
