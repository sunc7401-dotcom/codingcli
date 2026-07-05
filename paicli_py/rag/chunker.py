"""代码分块器。

对应 ``com.paicli.rag.CodeChunker``。

对 Java/Python 文件进行 AST 级别的类/方法分块，
对其他文件按行分割（每块 2000 字符）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class CodeChunk:
    """单个代码分块。"""
    file_path: str
    chunk_type: str  # "file" | "class" | "method" | "function" | "block"
    name: str
    content: str
    start_line: int = 0
    end_line: int = 0

    def to_embedding_text(self) -> str:
        """生成用于嵌入的文本表示。"""
        return f"[{self.chunk_type}:{self.name}] {self.content[:1500]}"


class CodeChunker:
    """按语言选择合适的策略进行代码分块。"""

    # 支持 AST 分块的语言
    _AST_LANGUAGES = {".java", ".py"}

    @classmethod
    def chunk_file(cls, file_path: Path) -> list[CodeChunk]:
        """将单个文件拆分为代码分块。"""
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []

        suffix = file_path.suffix.lower()

        if suffix in cls._AST_LANGUAGES:
            return cls._chunk_with_ast(file_path, text)
        else:
            return cls._chunk_by_lines(file_path, text)

    @classmethod
    def _chunk_with_ast(cls, file_path: Path, text: str) -> list[CodeChunk]:
        """使用 AST 进行分块。"""
        chunks: list[CodeChunk] = []
        lines = text.splitlines()
        rel_path = str(file_path)

        suffix = file_path.suffix.lower()
        if suffix == ".py":
            chunks = cls._chunk_python(rel_path, text, lines)
        else:
            # 降级为按行分块
            chunks = cls._chunk_by_lines(file_path, text)

        return chunks

    @classmethod
    def _chunk_python(cls, rel_path: str, text: str, lines: list[str]) -> list[CodeChunk]:
        """Python AST 分块：按类和函数拆分。"""
        try:
            import ast
        except ImportError:
            return cls._chunk_by_line_strategy(rel_path, text, 2000)

        chunks: list[CodeChunk] = []

        try:
            tree = ast.parse(text)
        except SyntaxError:
            # 语法错误时降级为按行分块
            return cls._chunk_by_line_strategy(rel_path, text, 2000)

        # 添加文件级分块
        chunks.append(CodeChunk(
            file_path=rel_path,
            chunk_type="file",
            name=rel_path,
            content=text[:2000],
            start_line=1,
            end_line=len(lines),
        ))

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef):
                start = node.lineno
                end = node.end_lineno or (start + len(node.body))
                snippet = "\n".join(lines[start - 1:end])
                chunks.append(CodeChunk(
                    file_path=rel_path,
                    chunk_type="function",
                    name=node.name,
                    content=snippet[:2000],
                    start_line=start,
                    end_line=end,
                ))
            elif isinstance(node, ast.ClassDef):
                start = node.lineno
                end = node.end_lineno or (start + len(node.body))
                snippet = "\n".join(lines[start - 1:end])
                chunks.append(CodeChunk(
                    file_path=rel_path,
                    chunk_type="class",
                    name=node.name,
                    content=snippet[:2000],
                    start_line=start,
                    end_line=end,
                ))

        return chunks

    @classmethod
    def _chunk_by_lines(cls, file_path: Path, text: str) -> list[CodeChunk]:
        """按行分块（每块最多 2000 字符）。"""
        return cls._chunk_by_line_strategy(str(file_path), text, 2000)

    @staticmethod
    def _chunk_by_line_strategy(file_path: str, text: str, max_chars: int = 2000) -> list[CodeChunk]:
        """纯按行 + 字符数分块。"""
        lines = text.splitlines()
        chunks: list[CodeChunk] = []
        current: list[str] = []
        current_chars = 0
        chunk_idx = 0

        for line in lines:
            if current_chars + len(line) > max_chars and current:
                chunk_idx += 1
                chunks.append(CodeChunk(
                    file_path=file_path,
                    chunk_type="block",
                    name=f"{file_path}#{chunk_idx}",
                    content="\n".join(current),
                ))
                current = []
                current_chars = 0
            current.append(line)
            current_chars += len(line) + 1  # +1 for newline

        if current:
            chunk_idx += 1
            chunks.append(CodeChunk(
                file_path=file_path,
                chunk_type="block",
                name=f"{file_path}#{chunk_idx}",
                content="\n".join(current),
            ))

        return chunks
