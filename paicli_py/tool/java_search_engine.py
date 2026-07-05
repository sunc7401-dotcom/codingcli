"""Java 代码检索引擎 —— 纯 Python 实现（对齐 Java JavaCodeSearchEngine）。

对应 ``com.paicli.tool.JavaCodeSearchEngine``。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

MAX_SEARCH_FILE_BYTES = 2 * 1024 * 1024  # 2MB
EXCLUDED_DIRS = {".git", ".paicli", "target", "node_modules", "dist", "build", "coverage", ".idea", ".gradle"}


@dataclass
class GrepMatch:
    file_path: str
    line_number: int
    context: list["ContextLine"]


@dataclass
class ContextLine:
    line_number: int
    content: str


@dataclass
class CodeSearchRequest:
    query: str
    project_root: Path
    root: Path
    regex: bool = False
    case_sensitive: bool = True
    glob: str | None = None
    max_results: int = 50
    head_limit: int = 20
    context_lines: int = 0


@dataclass
class CodeSearchResult:
    engine: str
    matches: list[GrepMatch]
    partial: bool = False
    partial_reason: str = ""


class JavaCodeSearchEngine:
    """逐文件 Java 代码检索引擎（降级方案）。"""

    def search(self, request: CodeSearchRequest) -> CodeSearchResult:
        try:
            flags = 0 if request.case_sensitive else re.IGNORECASE | re.UNICODE
            pattern = re.compile(request.query if request.regex else re.escape(request.query), flags)
        except re.error as e:
            return CodeSearchResult(engine="java", matches=[], partial=True, partial_reason=f"正则无效: {e}")

        matches: list[GrepMatch] = []
        per_file: dict[str, int] = {}
        head_limited = False

        for file_path in request.root.rglob("*"):
            if matches and len(matches) >= request.max_results:
                break
            if not file_path.is_file():
                continue
            if any(ex in file_path.parts for ex in EXCLUDED_DIRS):
                continue
            if file_path.stat().st_size > MAX_SEARCH_FILE_BYTES:
                continue
            if self._is_likely_binary(file_path):
                continue
            if request.glob and not file_path.match(request.glob):
                continue

            try:
                lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
                rel = str(file_path.relative_to(request.project_root))
                for i, line in enumerate(lines):
                    if len(matches) >= request.max_results:
                        break
                    fc = per_file.get(rel, 0)
                    if fc >= request.head_limit:
                        if pattern.search(line):
                            head_limited = True
                        continue
                    if pattern.search(line):
                        ctx_from = max(0, i - request.context_lines)
                        ctx_to = min(len(lines) - 1, i + request.context_lines)
                        ctx = [ContextLine(j + 1, lines[j]) for j in range(ctx_from, ctx_to + 1)]
                        matches.append(GrepMatch(rel, i + 1, ctx))
                        per_file[rel] = fc + 1
            except Exception:
                continue

        partial = len(matches) >= request.max_results or head_limited
        reason = "达到 max_results" if len(matches) >= request.max_results else "达到 head_limit" if head_limited else ""
        return CodeSearchResult(engine="java", matches=matches, partial=partial, partial_reason=reason)

    @staticmethod
    def _is_likely_binary(file_path: Path) -> bool:
        try:
            data = file_path.read_bytes()[:4096]
            return b"\x00" in data
        except OSError:
            return True
