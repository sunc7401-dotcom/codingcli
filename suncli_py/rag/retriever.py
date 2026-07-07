"""代码检索器 —— 语义检索 + 关键词检索 + 图谱检索的统一入口。

对应 ``com.paicli.rag.CodeRetriever``。

实现混合检索策略：
1. 语义检索（余弦相似度）
2. 关键词检索（SQL LIKE）
3. 双命中奖励（+0.1）
4. 代码类型加分（method +0.15, class +0.10）
5. 每文件最多 2 条结果
"""

from __future__ import annotations

from pathlib import Path

from suncli_py.rag.embedding import EmbeddingClient
from suncli_py.rag.vector_store import VectorStore


class CodeRetriever:
    """统一代码检索入口。

    使用示例::

        retriever = CodeRetriever("/path/to/project")
        results = await retriever.hybrid_search("authentication", top_k=10)
        relations = retriever.get_relation_graph("UserService")
    """

    def __init__(self, project_path: str, embedding_client: EmbeddingClient | None = None) -> None:
        self._embedding_client = embedding_client or EmbeddingClient()
        db_path = str(Path(project_path).resolve() / ".paicli" / "code_index.db")
        self._vector_store = VectorStore(db_path)

    # ── 语义检索 ────────────────────────────────────────────

    async def semantic_search(self, query: str, top_k: int = 10) -> list[dict]:
        """用自然语言查询最相关的代码块。"""
        query_emb = await self._embedding_client.embed(query)
        return self._vector_store.semantic_search(query_emb, top_k)

    # ── 关键词检索 ──────────────────────────────────────────

    def keyword_search(self, keyword: str) -> list[dict]:
        """按类名/方法名/内容精确匹配。"""
        return self._vector_store.keyword_search(keyword)

    # ── 混合检索 ────────────────────────────────────────────

    async def hybrid_search(self, query: str, top_k: int = 10) -> list[dict]:
        """混合检索：语义 + 关键词，去重合并，带奖励机制。

        策略（与 Java 版完全一致）：
        1. 语义检索 2*top_k 条候选
        2. 关键词检索（对每个分词独立查询）
        3. 双命中奖励 +0.1
        4. 代码类型加分：method +0.15, class +0.10
        5. 合并去重，每文件最多 2 条
        """
        from suncli_py.memory.query_tokenizer import tokenize

        merged: dict[str, dict] = {}
        dual_match_bonused: set[str] = set()

        # 1. 语义检索
        semantic_limit = max(top_k * 2, 10)
        try:
            for result in self._vector_store.semantic_search(
                await self._embedding_client.embed(query), semantic_limit
            ):
                self._merge_result(merged, result, dual_match_bonused)
        except Exception:
            pass

        # 2. 关键词检索
        keywords = tokenize(query)
        for keyword in keywords:
            for result in self._vector_store.keyword_search(keyword):
                boosted = self._boost_keyword_match(result, keyword)
                self._merge_result(merged, boosted, dual_match_bonused)

        # 3. 类型加分
        ranked: list[dict] = []
        for r in merged.values():
            chunk_type = r.get("chunk_type", "file")
            type_boost = {"method": 0.15, "class": 0.10}.get(chunk_type, 0.0)
            if type_boost > 0:
                r = {**r, "similarity": r.get("similarity", 0.0) + type_boost}
            ranked.append(r)

        ranked.sort(key=lambda x: x.get("similarity", 0.0), reverse=True)
        return self._limit_per_file(ranked, top_k, 2)

    # ── 内部算法 ────────────────────────────────────────────

    @staticmethod
    def _merge_result(merged: dict[str, dict], candidate: dict, dual_match_bonused: set[str]) -> None:
        key = f"{candidate.get('file_path', '')}#{candidate.get('name', '')}"
        existing = merged.get(key)
        sim = candidate.get("similarity", 0.0)

        if existing is None:
            merged[key] = dict(candidate)
        else:
            best = max(existing.get("similarity", 0.0), sim)
            if key not in dual_match_bonused:
                best += 0.1
                dual_match_bonused.add(key)
            merged[key] = {**candidate, "similarity": best}

    @staticmethod
    def _boost_keyword_match(result: dict, keyword: str) -> dict:
        name_lower = result.get("name", "").lower()
        file_lower = result.get("file_path", "").lower()
        content_lower = result.get("content", "").lower()
        kw_lower = keyword.lower()

        bonus = 0.0
        if kw_lower in name_lower:
            bonus += 0.3  # 类名/方法名精确命中是最强信号
        if kw_lower in file_lower:
            bonus += 0.1
        if kw_lower in content_lower:
            bonus += 0.1

        return {**result, "similarity": result.get("similarity", 0.0) + bonus}

    @staticmethod
    def _limit_per_file(sorted_results: list[dict], top_k: int, max_per_file: int) -> list[dict]:
        result: list[dict] = []
        file_counts: dict[str, int] = {}
        for r in sorted_results:
            fp = r.get("file_path", "")
            count = file_counts.get(fp, 0)
            if count < max_per_file:
                result.append(r)
                file_counts[fp] = count + 1
                if len(result) >= top_k:
                    break
        return result

    # ── 图谱检索 ────────────────────────────────────────────

    def get_relation_graph(self, name: str) -> list[dict]:
        """查询指定类/函数的关系图谱。"""
        return self._vector_store.get_relation_graph(name)

    def get_stats(self) -> dict:
        return self._vector_store.get_stats()

    def close(self) -> None:
        self._vector_store.close()
