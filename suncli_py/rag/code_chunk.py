"""代码分块模型 —— 对应 com.paicli.rag.CodeChunk。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CodeChunk:
    file_path: str
    chunk_type: str
    name: str
    content: str
    start_line: int = 0
    end_line: int = 0

    def to_embedding_text(self) -> str:
        return f"[{self.chunk_type}:{self.name}] {self.content[:1500]}"
