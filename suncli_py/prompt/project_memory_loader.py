"""项目记忆加载器 —— 读取 PAI.md（含 @import 支持）。

对应 ``com.paicli.prompt.ProjectMemoryLoader``。
"""

from __future__ import annotations

from pathlib import Path


class ProjectMemoryLoader:
    """加载项目级记忆文件。

    查找顺序（与 Java 一致）:
    1. ~/.paicli/PAI.md
    2. {project}/PAI.md
    3. {project}/.paicli/PAI.md
    4. {project}/PAI.local.md
    5. {project}/.paicli/PAI.local.md

    支持 @import 语法，最大递归深度 3 层，含循环检测。
    """

    MAX_TOTAL_CHARS = 24_000
    MAX_IMPORT_DEPTH = 3

    def __init__(self, project_root: str | None = None, user_config_dir: str | None = None) -> None:
        self._project_root = Path(project_root).resolve() if project_root else Path.cwd()
        self._user_config_dir = Path(user_config_dir) if user_config_dir else Path.home() / ".paicli"

    def load_for_prompt(self) -> str:
        """加载项目记忆内容（含 @import 展开）。

        Returns:
            带 "## PAI.md 项目记忆" 前缀的完整内容。
        """
        files = [
            self._user_config_dir / "PAI.md",
            self._project_root / "PAI.md",
            self._project_root / ".paicli" / "PAI.md",
            self._project_root / "PAI.local.md",
            self._project_root / ".paicli" / "PAI.local.md",
        ]

        import_stack: set[Path] = set()
        content = self._load_with_imports(files, import_stack, depth=0)

        if not content.strip():
            return ""

        truncated = content[:self.MAX_TOTAL_CHARS]
        if len(content) > self.MAX_TOTAL_CHARS:
            truncated += f"\n\n...(已截断，原 {len(content)} 字符)"
        return f"## PAI.md 项目记忆\n\n{truncated}"

    def _load_with_imports(self, files: list[Path], stack: set[Path], depth: int) -> str:
        """递归加载文件并展开 @import。"""
        if depth > self.MAX_IMPORT_DEPTH:
            return ""

        parts: list[str] = []
        for file_path in files:
            if not file_path.is_file():
                continue
            if file_path in stack:
                continue  # 循环检测

            try:
                text = file_path.read_text(encoding="utf-8")
            except OSError:
                continue

            stack.add(file_path)

            # 展开 @import 指令
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("@") and not stripped.startswith("@@"):
                    import_name = stripped[1:].strip()
                    # 安全校验：拒绝绝对路径和 .. 穿越（与 Java 一致）
                    if import_name.startswith("/") or ".." in import_name:
                        continue
                    if import_name:
                        import_path = file_path.parent / import_name
                        imported = self._load_with_imports([import_path], stack, depth + 1)
                        if imported:
                            parts.append(imported)
                else:
                    parts.append(line)

        return "\n".join(parts)
