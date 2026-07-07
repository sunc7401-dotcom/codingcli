"""Ripgrep 代码检索引擎 —— 对应 com.paicli.tool.RipgrepCodeSearchEngine。"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass


@dataclass
class GrepMatch:
    file_path: str
    line_number: int
    line_content: str
    context_before: list[str] | None = None
    context_after: list[str] | None = None


class RipgrepCodeSearchEngine:
    async def search(self, pattern: str, path: str = ".", glob: str | None = None, max_results: int = 200) -> list[GrepMatch]:
        try:
            proc = await asyncio.create_subprocess_exec("rg", "--line-number", "--no-heading", "--color=never", "-C", "2", "--max-count", str(max_results), *(["-g", glob] if glob else []), pattern, path, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, _ = await proc.communicate()
            output = stdout.decode("utf-8", errors="replace")
        except FileNotFoundError:
            return []
        results: list[GrepMatch] = []
        for line in output.splitlines():
            m = re.match(r"^(.+?):(\d+):(.*)$", line)
            if m:
                results.append(GrepMatch(file_path=m.group(1), line_number=int(m.group(2)), line_content=m.group(3)))
        return results[:max_results]
