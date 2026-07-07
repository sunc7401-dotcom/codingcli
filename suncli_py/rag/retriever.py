"""Unified RAG retrieval entry point."""

from __future__ import annotations

from pathlib import Path

from suncli_py.rag.embedding import EmbeddingClient
from suncli_py.rag.query_tokenizer import tokenize
from suncli_py.rag.vector_store import VectorStore


class CodeRetriever:
    """Semantic, keyword, hybrid, and relation-graph retrieval."""

    def __init__(self, project_path: str, embedding_client: EmbeddingClient | None = None) -> None:
        self._project_path = str(Path(project_path).resolve())
        self._embedding_client = embedding_client or EmbeddingClient()
        self._vector_store = VectorStore()

    async def semantic_search(self, query: str, top_k: int = 10) -> list[dict]:
        query_emb = await self._embedding_client.embed(query)
        return self._vector_store.semantic_search(query_emb, top_k, self._project_path)

    def keyword_search(self, keyword: str, limit: int = 10) -> list[dict]:
        return self._vector_store.keyword_search(keyword, limit, self._project_path)

    async def hybrid_search(self, query: str, top_k: int = 10) -> list[dict]:
        merged: dict[str, dict] = {}
        dual_match_bonused: set[str] = set()

        semantic_limit = max(top_k * 2, 10)
        try:
            query_emb = await self._embedding_client.embed(query)
            for result in self._vector_store.semantic_search(query_emb, semantic_limit, self._project_path):
                self._merge_result(merged, result, dual_match_bonused)
        except Exception:
            pass

        for keyword in tokenize(query):
            for result in self._vector_store.keyword_search(keyword, top_k * 2, self._project_path):
                self._merge_result(merged, self._boost_keyword_match(result, keyword), dual_match_bonused)

        ranked: list[dict] = []
        for result in merged.values():
            chunk_type = result.get("chunk_type", "file")
            type_boost = {"method": 0.15, "function": 0.15, "class": 0.10}.get(chunk_type, 0.0)
            ranked.append({**result, "similarity": result.get("similarity", 0.0) + type_boost})

        ranked.sort(key=lambda x: x.get("similarity", 0.0), reverse=True)
        return self._limit_per_file(ranked, top_k, 2)

    def get_relation_graph(self, name: str) -> list[dict]:
        return self._vector_store.get_relation_graph(name, self._project_path)

    def get_stats(self) -> dict[str, int]:
        return self._vector_store.get_stats(self._project_path)

    def close(self) -> None:
        self._vector_store.close()

    @staticmethod
    def _merge_result(merged: dict[str, dict], candidate: dict, dual_match_bonused: set[str]) -> None:
        key = f"{candidate.get('file_path', '')}#{candidate.get('name', '')}"
        existing = merged.get(key)
        sim = candidate.get("similarity", 0.0)

        if existing is None:
            merged[key] = dict(candidate)
            return

        best = max(existing.get("similarity", 0.0), sim)
        if key not in dual_match_bonused:
            best += 0.1
            dual_match_bonused.add(key)
        merged[key] = {**candidate, "similarity": best}

    @staticmethod
    def _boost_keyword_match(result: dict, keyword: str) -> dict:
        name_lower = str(result.get("name", "")).lower()
        file_lower = str(result.get("file_path", "")).lower()
        content_lower = str(result.get("content", "")).lower()
        keyword_lower = keyword.lower()

        bonus = 0.0
        if keyword_lower in name_lower:
            bonus += 0.3
        if keyword_lower in file_lower:
            bonus += 0.1
        if keyword_lower in content_lower:
            bonus += 0.1
        return {**result, "similarity": result.get("similarity", 0.0) + bonus}

    @staticmethod
    def _limit_per_file(sorted_results: list[dict], top_k: int, max_per_file: int) -> list[dict]:
        results: list[dict] = []
        file_counts: dict[str, int] = {}
        for item in sorted_results:
            file_path = item.get("file_path", "")
            count = file_counts.get(file_path, 0)
            if count >= max_per_file:
                continue
            results.append(item)
            file_counts[file_path] = count + 1
            if len(results) >= top_k:
                break
        return results
