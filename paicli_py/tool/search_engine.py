"""代码检索引擎 —— ripgrep 封装。

对应 ``com.paicli.tool.RipgrepCodeSearchEngine`` 和 ``CodeSearchEngine`` 接口。
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

# 搜索时排除的目录
EXCLUDED_DIRS: set[str] = {
    ".git", ".paicli", "target", "node_modules", "dist",
    "build", "coverage", ".idea", ".gradle", "__pycache__",
    ".venv", "venv", ".tox", ".mypy_cache", ".ruff_cache",
}

# 默认最大结果数
DEFAULT_MAX_RESULTS = 200
DEFAULT_CONTEXT_LINES = 5
DEFAULT_MAX_CHARS = 24_000
MAX_MAX_CHARS = 60_000


@dataclass
class CodeSearchMatch:
    """单条代码搜索结果。"""
    file_path: str
    line_number: int
    line_content: str
    context_before: list[str]
    context_after: list[str]


@runtime_checkable
class CodeSearchEngine(Protocol):
    """代码检索引擎协议。"""

    async def search(
        self,
        pattern: str,
        path: str | None = None,
        include: str | None = None,
        max_results: int = DEFAULT_MAX_RESULTS,
        context_lines: int = DEFAULT_CONTEXT_LINES,
    ) -> list[CodeSearchMatch]:
        """执行代码搜索。"""
        ...


class RipgrepCodeSearchEngine(CodeSearchEngine):
    """基于 ripgrep (rg) 的代码检索引擎。

    如果系统没有安装 rg，则降级为 Python 内置的逐行搜索。
    """

    async def search(
        self,
        pattern: str,
        path: str | None = None,
        include: str | None = None,
        max_results: int = DEFAULT_MAX_RESULTS,
        context_lines: int = DEFAULT_CONTEXT_LINES,
    ) -> list[CodeSearchMatch]:
        search_path = path or "."

        # 优先使用 ripgrep
        if self._has_rg():
            return await self._rg_search(pattern, search_path, include, max_results, context_lines)
        else:
            return await self._fallback_search(pattern, search_path, include, max_results, context_lines)

    @staticmethod
    def _has_rg() -> bool:
        """检查系统是否安装了 ripgrep。"""
        import shutil
        return shutil.which("rg") is not None

    async def _rg_search(
        self,
        pattern: str,
        path: str,
        include: str | None,
        max_results: int,
        context_lines: int,
    ) -> list[CodeSearchMatch]:
        """通过 ripgrep 子进程搜索。"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "rg",
                "--line-number",
                "--no-heading",
                "--color=never",
                "-C", str(context_lines),
                "--max-count", str(max_results),
                *(["-g", include] if include else []),
                pattern,
                path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            return self._parse_rg_output(stdout.decode("utf-8", errors="replace"))
        except FileNotFoundError:
            return await self._fallback_search(pattern, path, include, max_results, context_lines)

    @staticmethod
    def _parse_rg_output(output: str) -> list[CodeSearchMatch]:
        """解析 ripgrep 输出。格式: file:line:content"""
        results: list[CodeSearchMatch] = []
        for line in output.splitlines():
            match = re.match(r"^(.+?):(\d+):(.*)$", line)
            if match:
                results.append(CodeSearchMatch(
                    file_path=match.group(1),
                    line_number=int(match.group(2)),
                    line_content=match.group(3),
                    context_before=[],
                    context_after=[],
                ))
        return results

    async def _fallback_search(
        self,
        pattern: str,
        path: str,
        include: str | None,
        max_results: int,
        context_lines: int,
    ) -> list[CodeSearchMatch]:
        """降级方案：Python 逐文件搜索。"""
        results: list[CodeSearchMatch] = []
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error:
            return results

        base = Path(path).resolve()
        if not base.exists():
            return results

        for file_path in base.rglob("*"):
            if file_path.is_dir():
                if file_path.name in EXCLUDED_DIRS or file_path.name.startswith("."):
                    continue
                continue

            # 只搜索文本文件
            if not _is_text_file(file_path):
                continue

            # glob 过滤
            if include and not file_path.match(include):
                continue

            try:
                lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
                for i, line in enumerate(lines, start=1):
                    if compiled.search(line):
                        results.append(CodeSearchMatch(
                            file_path=str(file_path.relative_to(base)),
                            line_number=i,
                            line_content=line,
                            context_before=lines[max(0, i - context_lines - 1):i - 1],
                            context_after=lines[i:min(len(lines), i + context_lines)],
                        ))
                        if len(results) >= max_results:
                            return results
            except (OSError, UnicodeDecodeError):
                continue

        return results


def _is_text_file(file_path: Path) -> bool:
    """快速判断文件是否为文本格式。"""
    text_extensions = {
        ".py", ".java", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".c", ".cpp",
        ".h", ".hpp", ".cs", ".rb", ".php", ".swift", ".kt", ".scala", ".clj",
        ".html", ".css", ".scss", ".less", ".xml", ".json", ".yaml", ".yml",
        ".toml", ".ini", ".cfg", ".conf", ".md", ".rst", ".txt", ".sh", ".bash",
        ".zsh", ".fish", ".ps1", ".bat", ".sql", ".r", ".m", ".mm", ".vue",
        ".svelte", ".astro", ".graphql", ".proto", ".env",
    }
    return file_path.suffix.lower() in text_extensions
