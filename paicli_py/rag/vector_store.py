"""SQLite 向量存储 —— 代码分块 + 嵌入 + 关系图。

对应 ``com.paicli.rag.VectorStore``。

表结构:
- code_chunks: 代码分块 + 嵌入向量 (JSON)
- code_relations: 代码关系图 (extends/implements/calls/contains)
"""

from __future__ import annotations

import json
import math
import sqlite3
from typing import Any


class VectorStore:
    """基于 SQLite 的代码向量存储。

    使用内存中的余弦相似度计算进行语义搜索，
    通过 LIKE 进行关键词搜索，
    两者结果合并为混合搜索。
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS code_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_path TEXT NOT NULL,
                file_path TEXT NOT NULL,
                chunk_type TEXT NOT NULL,
                name TEXT,
                content TEXT NOT NULL,
                start_line INTEGER,
                end_line INTEGER,
                embedding_json TEXT
            );
            CREATE TABLE IF NOT EXISTS code_relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_file TEXT NOT NULL,
                from_name TEXT,
                to_file TEXT NOT NULL,
                to_name TEXT,
                relation_type TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_project ON code_chunks(project_path);
            CREATE INDEX IF NOT EXISTS idx_chunks_file ON code_chunks(file_path);
            CREATE INDEX IF NOT EXISTS idx_relations_from ON code_relations(from_file);
        """)
        self._conn.commit()

    # ── 写入 ────────────────────────────────────────────────

    def insert_chunk(
        self,
        project_path: str,
        file_path: str,
        chunk_type: str,
        name: str | None,
        content: str,
        start_line: int = 0,
        end_line: int = 0,
        embedding: list[float] | None = None,
    ) -> int:
        embedding_json = json.dumps(embedding) if embedding else None
        cur = self._conn.execute(
            "INSERT INTO code_chunks (project_path, file_path, chunk_type, name, content, start_line, end_line, embedding_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [project_path, file_path, chunk_type, name, content, start_line, end_line, embedding_json],
        )
        self._conn.commit()
        return cur.lastrowid

    def insert_relation(self, from_file: str, from_name: str | None, to_file: str, to_name: str | None, relation_type: str) -> None:
        self._conn.execute(
            "INSERT INTO code_relations (from_file, from_name, to_file, to_name, relation_type) VALUES (?, ?, ?, ?, ?)",
            [from_file, from_name, to_file, to_name, relation_type],
        )
        self._conn.commit()

    def delete_by_project(self, project_path: str) -> None:
        self._conn.execute("DELETE FROM code_chunks WHERE project_path = ?", [project_path])
        self._conn.commit()

    # ── 语义搜索 ────────────────────────────────────────────

    def semantic_search(self, query_embedding: list[float], top_k: int = 10) -> list[dict[str, Any]]:
        """基于余弦相似度的语义搜索。"""
        rows = self._conn.execute(
            "SELECT id, file_path, chunk_type, name, content, start_line, embedding_json FROM code_chunks WHERE embedding_json IS NOT NULL"
        ).fetchall()

        scored: list[tuple[float, dict]] = []
        for row in rows:
            emb = json.loads(row["embedding_json"])
            similarity = self._cosine_similarity(query_embedding, emb)
            scored.append((similarity, dict(row)))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:top_k]]

    def keyword_search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """基于 SQL LIKE 的关键词搜索（转义 % 和 _，与 Java 一致）。"""
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        rows = self._conn.execute(
            "SELECT id, file_path, chunk_type, name, content, start_line FROM code_chunks WHERE content LIKE ? ESCAPE '\\' LIMIT ?",
            [f"%{escaped}%", limit],
        ).fetchall()
        return [dict(r) for r in rows]

    def hybrid_search(self, query: str, query_embedding: list[float] | None = None, top_k: int = 10) -> list[dict[str, Any]]:
        """混合搜索：语义 + 关键词，去重合并，每文件最多 2 条结果。"""
        semantic_results: list[dict] = []
        if query_embedding:
            semantic_results = self.semantic_search(query_embedding, top_k * 2)

        keyword_results = self.keyword_search(query, top_k)

        # 合并去重
        seen_ids: set[int] = set()
        file_counts: dict[str, int] = {}
        merged: list[dict] = []

        # 语义结果优先
        for item in semantic_results + keyword_results:
            item_id = item["id"]
            file_path = item["file_path"]

            if item_id in seen_ids:
                continue

            fc = file_counts.get(file_path, 0)
            if fc >= 2:  # 每文件最多 2 条
                continue

            seen_ids.add(item_id)
            file_counts[file_path] = fc + 1
            merged.append(item)

            if len(merged) >= top_k:
                break

        return merged

    def get_relation_graph(self, class_name: str) -> list[dict[str, Any]]:
        """获取代码关系图。"""
        rows = self._conn.execute(
            "SELECT * FROM code_relations WHERE from_name = ? OR to_name = ?",
            [class_name, class_name],
        ).fetchall()
        return [dict(r) for r in rows]

    def get_stats(self) -> dict[str, int]:
        """获取索引统计。"""
        chunks = self._conn.execute("SELECT COUNT(*) as cnt FROM code_chunks").fetchone()["cnt"]
        relations = self._conn.execute("SELECT COUNT(*) as cnt FROM code_relations").fetchone()["cnt"]
        return {"chunks": chunks, "relations": relations}

    def close(self) -> None:
        self._conn.close()

    # ── 内部 ────────────────────────────────────────────────

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        if len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
