"""提示词模板仓库 —— 从磁盘加载 Markdown 模板。

对应 ``com.paicli.prompt.PromptRepository``。
"""

from __future__ import annotations

from pathlib import Path


class PromptRepository:
    """从 resources/prompts/ 目录加载 Markdown 模板。"""

    def __init__(self, prompts_dir: str | None = None) -> None:
        self._dir = Path(prompts_dir) if prompts_dir else Path(__file__).parent.parent / "resources" / "prompts"
        self._cache: dict[str, str] = {}

    def load(self, name: str) -> str:
        """按名称加载模板文件（不含 .md 后缀）。"""
        if name in self._cache:
            return self._cache[name]

        file_path = self._dir / f"{name}.md"
        if file_path.is_file():
            content = file_path.read_text(encoding="utf-8")
            self._cache[name] = content
            return content

        # 尝试子目录
        for sub in self._dir.iterdir():
            if sub.is_dir():
                candidate = sub / f"{name}.md"
                if candidate.is_file():
                    content = candidate.read_text(encoding="utf-8")
                    self._cache[name] = content
                    return content

        return ""
