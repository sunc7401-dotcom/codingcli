"""显式记忆提示检测 —— 识别用户"记住"意图。

对应 ``com.paicli.memory.ExplicitMemoryHints``。
用于浏览器登录等场景中自动提取关键信息。
"""

from __future__ import annotations

# 触发"记住"意图的关键词模式
_REMEMBER_PATTERNS = [
    "记住",
    "记一下",
    "保存下来",
    "别忘了",
    "保存偏好",
    "记住这个",
    "记下来",
]


def is_explicit_remember(text: str) -> bool:
    """检查文本是否包含明确的"记住"意图。"""
    text_lower = text.lower()
    return any(pattern in text_lower for pattern in _REMEMBER_PATTERNS)


def extract_fact_from_remember(text: str) -> str | None:
    """从"记住"语句中提取事实内容。

    例如: "记住我喜欢用 dark mode" → "用户偏好 dark mode"
    """
    if not is_explicit_remember(text):
        return None

    # 简单提取：去掉触发词后的内容
    for pattern in _REMEMBER_PATTERNS:
        idx = text.find(pattern)
        if idx >= 0:
            fact = text[idx + len(pattern):].strip().lstrip("，,：:。.")
            if fact:
                return fact
    return None
