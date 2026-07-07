"""jieba 分词工厂 —— 对应 ``com.paicli.util.JiebaSegmenterFactory``。"""

from __future__ import annotations


def get_segmenter():
    """获取 jieba 分词器实例（抑制字典加载噪声，与 Java 一致）。"""
    import jieba
    return jieba  # Python jieba 模块本身即为单例，等价于 Java 的 JiebaSegmenter
