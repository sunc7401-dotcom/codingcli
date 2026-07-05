"""@image: 引用解析器。

对应 ``com.paicli.image.ImageReferenceParser``。
"""

from __future__ import annotations

import re
from pathlib import Path


class ImageReferenceParser:
    """解析用户输入中的 @image:path 引用。"""

    _PATTERN = re.compile(r"@image:(\S+)")

    @classmethod
    def parse(cls, text: str) -> list[Path]:
        """提取所有 @image: 引用的文件路径。"""
        paths: list[Path] = []
        for match in cls._PATTERN.finditer(text):
            p = Path(match.group(1))
            if p.is_file():
                paths.append(p)
        return paths

    @classmethod
    def expand(cls, text: str, project_root: str | None = None) -> str:
        """将 @image:path 替换为内联 base64 图片数据。

        此处暂不做替换——完整的 base64 内联由 Agent 层处理。
        """
        return text
