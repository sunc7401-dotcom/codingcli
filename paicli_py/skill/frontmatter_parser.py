"""YAML frontmatter 解析器 —— 对应 ``com.paicli.skill.SkillFrontmatterParser``。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass
class ParseResult:
    frontmatter: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    warnings: list[str] = field(default_factory=list)


def parse_frontmatter(text: str) -> ParseResult:
    """解析 SKILL.md 文件开头的 YAML frontmatter。

    Returns:
        ParseResult(frontmatter, body, warnings) — 与 Java 返回类型一致。
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return ParseResult(body=text)

    yaml_block = match.group(1)
    body = text[match.end():]
    fm: dict[str, Any] = {}
    warnings: list[str] = []

    try:
        import yaml
        parsed = yaml.safe_load(yaml_block)
        if isinstance(parsed, dict):
            fm = parsed
    except Exception as e:
        warnings.append(f"YAML 解析异常: {e}")

    return ParseResult(frontmatter=fm, body=body, warnings=warnings)
