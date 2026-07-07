"""SQLite-backed code chunk store for RAG search."""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from typing import Any


def default_db_path() -> str:
    """Return the shared PaiCLI RAG database path."""
    return str(Path.home() / ".paicli" / "rag" / "codebase.db")


class VectorStore:
    """Stores code chunks, embeddings, and code relations in SQLite."""

    def __init__(self, db_path: str | None = None) -> None:
        db_path = db_path or default_db_path()
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript(
            """
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
                project_path TEXT,
                from_file TEXT NOT NULL,
                from_name TEXT,
                to_file TEXT NOT NULL,
                to_name TEXT,
                relation_type TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_project ON code_chunks(project_path);
            CREATE INDEX IF NOT EXISTS idx_chunks_file ON code_chunks(file_path);
            CREATE INDEX IF NOT EXISTS idx_chunks_type ON code_chunks(chunk_type);
            CREATE INDEX IF NOT EXISTS idx_relations_project ON code_relations(project_path);
            CREATE INDEX IF NOT EXISTS idx_relations_from ON code_relations(from_name);
            CREATE INDEX IF NOT EXISTS idx_relations_to ON code_relations(to_name);
            """
        )

        columns = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(code_relations)").fetchall()
        }
        if "project_path" not in columns:
            self._conn.execute("ALTER TABLE code_relations ADD COLUMN project_path TEXT")
        self._conn.commit()

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
            """
            INSERT INTO code_chunks
                (project_path, file_path, chunk_type, name, content, start_line, end_line, embedding_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [project_path, file_path, chunk_type, name, content, start_line, end_line, embedding_json],
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def insert_relation(
        self,
        project_path: str,
        from_file: str,
        from_name: str | None,
        to_file: str,
        to_name: str | None,
        relation_type: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO code_relations
                (project_path, from_file, from_name, to_file, to_name, relation_type)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [project_path, from_file, from_name, to_file, to_name, relation_type],
        )
        self._conn.commit()

    def delete_by_project(self, project_path: str) -> None:
        self._conn.execute("DELETE FROM code_chunks WHERE project_path = ?", [project_path])
        self._conn.execute("DELETE FROM code_relations WHERE project_path = ?", [project_path])
        self._conn.commit()

    def semantic_search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        project_path: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT id, project_path, file_path, chunk_type, name, content, start_line, end_line, embedding_json "
            "FROM code_chunks WHERE embedding_json IS NOT NULL"
        )
        params: list[Any] = []
        if project_path:
            sql += " AND project_path = ?"
            params.append(project_path)

        rows = self._conn.execute(sql, params).fetchall()
        scored: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            emb = json.loads(row["embedding_json"])
            similarity = self._cosine_similarity(query_embedding, emb)
            item = dict(row)
            item["similarity"] = similarity
            item.pop("embedding_json", None)
            scored.append((similarity, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:top_k]]

    def keyword_search(
        self,
        query: str,
        limit: int = 10,
        project_path: str | None = None,
    ) -> list[dict[str, Any]]:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
        sql = (
            "SELECT id, project_path, file_path, chunk_type, name, content, start_line, end_line "
            "FROM code_chunks "
            "WHERE (content LIKE ? ESCAPE '\\' OR name LIKE ? ESCAPE '\\' OR file_path LIKE ? ESCAPE '\\')"
        )
        params: list[Any] = [like, like, like]
        if project_path:
            sql += " AND project_path = ?"
            params.append(project_path)
        sql += " LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(sql, params).fetchall()
        return [{**dict(r), "similarity": 0.0} for r in rows]

    def hybrid_search(
        self,
        query: str,
        query_embedding: list[float] | None = None,
        top_k: int = 10,
        project_path: str | None = None,
    ) -> list[dict[str, Any]]:
        semantic_results: list[dict[str, Any]] = []
        if query_embedding:
            semantic_results = self.semantic_search(query_embedding, top_k * 2, project_path)

        keyword_results = self.keyword_search(query, top_k, project_path)

        seen_ids: set[int] = set()
        file_counts: dict[str, int] = {}
        merged: list[dict[str, Any]] = []
        for item in semantic_results + keyword_results:
            item_id = int(item["id"])
            file_path = item["file_path"]
            if item_id in seen_ids:
                continue
            if file_counts.get(file_path, 0) >= 2:
                continue
            seen_ids.add(item_id)
            file_counts[file_path] = file_counts.get(file_path, 0) + 1
            merged.append(item)
            if len(merged) >= top_k:
                break

        return merged

    def get_relation_graph(self, class_name: str, project_path: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM code_relations WHERE (from_name = ? OR to_name = ?)"
        params: list[Any] = [class_name, class_name]
        if project_path:
            sql += " AND project_path = ?"
            params.append(project_path)
        rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_stats(self, project_path: str | None = None) -> dict[str, int]:
        if project_path:
            chunks = self._conn.execute(
                "SELECT COUNT(*) AS cnt FROM code_chunks WHERE project_path = ?",
                [project_path],
            ).fetchone()["cnt"]
            relations = self._conn.execute(
                "SELECT COUNT(*) AS cnt FROM code_relations WHERE project_path = ?",
                [project_path],
            ).fetchone()["cnt"]
        else:
            chunks = self._conn.execute("SELECT COUNT(*) AS cnt FROM code_chunks").fetchone()["cnt"]
            relations = self._conn.execute("SELECT COUNT(*) AS cnt FROM code_relations").fetchone()["cnt"]
        return {"chunks": int(chunks), "relations": int(relations)}

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        if len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b, strict=False))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
