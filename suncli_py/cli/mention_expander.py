"""本地路径 @提及 展开器 —— 对应 ``com.paicli.cli.LocalPathMentionExpander``。

将 @path 格式的提及展开为内联文件内容。
"""

from __future__ import annotations

from pathlib import Path


class LocalPathMentionExpander:
    """将用户输入中的 @file_path 展开为内联文件内容。

    使用 XML 标签包装以区分文件和目录。
    """

    @staticmethod
    def expand(text: str, project_root: str | None = None) -> str:
        """展开 @path 提及。

        格式:
        - @file.py → ``<file path="file.py">\n内容\n</file>``
        - @dir/ → ``<dir path="dir/">\n文件列表\n</dir>``

        Returns:
            展开后的文本。
        """
        import re

        base = Path(project_root) if project_root else Path.cwd()

        def _replacer(match: re.Match) -> str:
            path_str = match.group(1)
            target = base / path_str

            try:
                if target.is_file():
                    content = target.read_text(encoding="utf-8", errors="replace")
                    return f'<file path="{path_str}">\n{content[:5000]}\n</file>'
                elif target.is_dir():
                    items = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name))
                    listing = "\n".join(
                        f"{'📁' if p.is_dir() else '📄'} {p.name}"
                        for p in items[:50]
                    )
                    return f'<dir path="{path_str}">\n{listing}\n</dir>'
            except OSError:
                pass

            return match.group(0)  # 保持原样

        # 匹配 @ 后跟路径的模式
        return re.sub(r"@(\S+)", _replacer, text)
