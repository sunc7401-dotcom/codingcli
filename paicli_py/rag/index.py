"""代码索引编排器 —— walk → chunk → embed → analyze → persist。

对应 ``com.paicli.rag.CodeIndex``。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from loguru import logger

from paicli_py.rag.analyzer import CodeAnalyzer, CodeRelation
from paicli_py.rag.chunker import CodeChunker
from paicli_py.rag.embedding import EmbeddingClient
from paicli_py.rag.vector_store import VectorStore

# 支持索引的文件扩展名
_INDEXABLE_EXTENSIONS = {
    ".py", ".java", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php", ".swift",
    ".kt", ".scala", ".clj", ".vue", ".svelte", ".astro", ".sql",
    ".sh", ".bash", ".ps1",
}

# 排除目录
_EXCLUDED_DIRS = {
    ".git", ".paicli", "node_modules", "__pycache__", "target",
    "build", "dist", ".venv", "venv", ".tox", ".mypy_cache",
}


class CodeIndex:
    """代码索引编排器。

    使用示例::

        index = CodeIndex(embedding_client)
        await index.index_project("/path/to/project", progress_callback)
        results = index.search("authentication", query_embedding)
    """

    def __init__(self, embedding_client: EmbeddingClient | None = None) -> None:
        self._vector_store = VectorStore()
        self._embedding_client = embedding_client

    async def index_project(
        self,
        project_path: str,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> None:
        """索引整个项目。

        *progress_callback*: (completed, total) → None
        """
        base = Path(project_path).resolve()
        self._vector_store.delete_by_project(str(base))

        # 收集文件
        files: list[Path] = []
        for file_path in base.rglob("*"):
            if file_path.is_dir():
                continue
            if any(excl in file_path.parts for excl in _EXCLUDED_DIRS):
                continue
            if file_path.suffix.lower() in _INDEXABLE_EXTENSIONS:
                files.append(file_path)

        total = len(files)
        logger.info(f"索引项目 {base.name}: {total} 个文件")

        relation_count = 0
        for i, file_path in enumerate(files):
            try:
                # 分析代码关系
                relations = CodeAnalyzer.analyze(file_path)
                for rel in relations:
                    self._vector_store.insert_relation(rel.from_file, rel.from_name, rel.to_file, rel.to_name, rel.relation_type)
                    relation_count += 1
            except Exception:
                pass

        for i, file_path in enumerate(files):
            try:
                # 分块
                chunks = CodeChunker.chunk_file(file_path)
                rel_path = str(file_path.relative_to(base))

                for chunk in chunks:
                    # 生成嵌入
                    emb = None
                    if self._embedding_client:
                        try:
                            emb = await self._embedding_client.embed(chunk.to_embedding_text())
                        except Exception:
                            pass

                    # 存储
                    self._vector_store.insert_chunk(
                        project_path=str(base),
                        file_path=rel_path,
                        chunk_type=chunk.chunk_type,
                        name=chunk.name,
                        content=chunk.content,
                        start_line=chunk.start_line,
                        end_line=chunk.end_line,
                        embedding=emb,
                    )

            except Exception as e:
                logger.warning(f"索引文件失败 {file_path}: {e}")

            if progress_callback:
                progress_callback(i + 1, total)

        logger.info(f"索引完成: {self._vector_store.get_stats()}")

    def search(
        self,
        query: str,
        query_embedding: list[float] | None = None,
        top_k: int = 10,
    ) -> list[dict]:
        """混合搜索。"""
        return self._vector_store.hybrid_search(query, query_embedding, top_k)

    def get_relation_graph(self, class_name: str) -> list[dict]:
        """获取代码关系图。"""
        return self._vector_store.get_relation_graph(class_name)

    def close(self) -> None:
        self._vector_store.close()
