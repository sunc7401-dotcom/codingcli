"""搜索结果格式化器 —— 对应 ``com.paicli.rag.SearchResultFormatter``。"""

from __future__ import annotations


def format_for_cli(query: str, results: list[dict], max_chars: int = 120) -> str:
    return _format_results(query, results, max_chars)


def format_for_tool(query: str, results: list[dict], max_chars: int = 180) -> str:
    return _format_results(query, results, max_chars)


def _format_results(query: str, results: list[dict], snippet_chars: int) -> str:
    if not results:
        return f"未找到与「{query}」相关的结果。"
    lines = [build_summary(query, results), ""]
    for i, r in enumerate(results[:10], 1):
        sim = r.get("similarity", 0)
        ctype = r.get("chunk_type", "file")
        name = r.get("name", "")
        path = _shorten_path(r.get("file_path", ""))
        snippet = _build_snippet(r.get("content", ""), snippet_chars)
        lines.append(f"  {i}. [{ctype}] {name} ({sim:.3f}) {path}")
        lines.append(f"     {snippet}")
    return "\n".join(lines)


def build_summary(query: str, results: list[dict]) -> str:
    """生成自然语言摘要（与 Java buildSummary 一致）。"""
    if not results:
        return f"未找到与「{query}」相关的结果。"
    best = results[0]
    ctype = best.get("chunk_type", "file")
    name = best.get("name", "?")
    path = _shorten_path(best.get("file_path", ""))
    files = list(dict.fromkeys(r.get("file_path", "") for r in results[:10]))[:3]
    from paicli_py.memory.query_tokenizer import tokenize
    tokens = tokenize(query)
    keywords = ", ".join(sorted(tokens)[:5]) if tokens else query
    return (
        f"最佳匹配: [{ctype}] {name} 位于 {path}。"
        f"相关结果集中在 {', '.join(files)} 等文件中。"
        f"排序依据关键词: {keywords}。"
    )


def _build_snippet(content: str, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + "..."


def _shorten_path(file_path: str, keep: int = 3) -> str:
    parts = file_path.replace("\\", "/").split("/")
    return "/".join(parts[-keep:]) if len(parts) > keep else file_path
