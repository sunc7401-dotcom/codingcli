"""Project code indexing orchestration for RAG."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from loguru import logger

from suncli_py.rag.analyzer import CodeAnalyzer
from suncli_py.rag.chunker import CodeChunker
from suncli_py.rag.embedding import EmbeddingClient
from suncli_py.rag.vector_store import VectorStore

_INDEXABLE_EXTENSIONS = {
    ".py", ".java", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php", ".swift",
    ".kt", ".scala", ".clj", ".vue", ".svelte", ".astro", ".sql",
    ".sh", ".bash", ".ps1", ".md", ".xml", ".properties", ".yaml",
    ".yml", ".json", ".gradle",
}

_EXCLUDED_DIRS = {
    ".git", ".paicli", "node_modules", "__pycache__", "target",
    "build", "dist", ".venv", "venv", ".tox", ".mypy_cache",
    ".pytest_cache", ".ruff_cache",
}


class CodeIndex:
    """Indexes a project into the shared RAG vector store."""

    def __init__(self, embedding_client: EmbeddingClient | None = None) -> None:
        self._vector_store = VectorStore()
        self._embedding_client = embedding_client

    async def index_project(
        self,
        project_path: str,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> dict[str, int]:
        base = Path(project_path).resolve()
        project_key = str(base)
        self._vector_store.delete_by_project(project_key)

        files = self._collect_files(base)
        total = len(files)
        logger.info(f"Indexing project {base}: {total} files")

        for file_path in files:
            try:
                for rel in CodeAnalyzer.analyze(file_path):
                    self._vector_store.insert_relation(
                        project_key,
                        rel.from_file,
                        rel.from_name,
                        rel.to_file,
                        rel.to_name,
                        rel.relation_type,
                    )
            except Exception as exc:
                logger.debug(f"Relation analysis failed for {file_path}: {exc}")

        for i, file_path in enumerate(files, 1):
            try:
                rel_path = str(file_path.relative_to(base))
                for chunk in CodeChunker.chunk_file(file_path):
                    embedding = None
                    if self._embedding_client:
                        try:
                            embedding = await self._embedding_client.embed(chunk.to_embedding_text())
                        except Exception as exc:
                            logger.debug(f"Embedding failed for {file_path}: {exc}")

                    self._vector_store.insert_chunk(
                        project_path=project_key,
                        file_path=rel_path,
                        chunk_type=chunk.chunk_type,
                        name=chunk.name,
                        content=chunk.content,
                        start_line=chunk.start_line,
                        end_line=chunk.end_line,
                        embedding=embedding,
                    )
            except Exception as exc:
                logger.warning(f"Indexing file failed {file_path}: {exc}")

            if progress_callback:
                progress_callback(i, total)

        stats = self._vector_store.get_stats(project_key)
        logger.info(f"Index complete: {stats}")
        return stats

    def search(
        self,
        query: str,
        query_embedding: list[float] | None = None,
        top_k: int = 10,
        project_path: str | None = None,
    ) -> list[dict]:
        project_key = str(Path(project_path).resolve()) if project_path else None
        return self._vector_store.hybrid_search(query, query_embedding, top_k, project_key)

    def get_relation_graph(self, class_name: str, project_path: str | None = None) -> list[dict]:
        project_key = str(Path(project_path).resolve()) if project_path else None
        return self._vector_store.get_relation_graph(class_name, project_key)

    def close(self) -> None:
        self._vector_store.close()

    @staticmethod
    def _collect_files(base: Path) -> list[Path]:
        if not base.exists():
            return []

        files: list[Path] = []
        for file_path in base.rglob("*"):
            if file_path.is_dir():
                continue
            if any(part in _EXCLUDED_DIRS for part in file_path.parts):
                continue
            if file_path.suffix.lower() in _INDEXABLE_EXTENSIONS:
                files.append(file_path)
        return files
