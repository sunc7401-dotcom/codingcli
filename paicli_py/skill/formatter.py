"""技能索引格式化器 —— 与 Java 版格式完全一致。

对应 ``com.paicli.skill.SkillIndexFormatter``。
"""

from __future__ import annotations

import sys

from paicli_py.skill.skill import Skill

MAX_ENABLED_SKILLS = 20
MAX_DESCRIPTION_CODEPOINTS = 500
MAX_INDEX_BYTES = 4096


def format_skill_index(skills: list[Skill]) -> str:
    """生成注入 system prompt 的技能索引段。

    格式与 Java 完全一致：
    ## 可用 Skills（按需调用 load_skill 加载完整指引）
    - **技能名**: 描述
    ...

    调用 load_skill(name) 即可加载完整指引。

    限制：最多 20 个技能，总长 4096 字节，单描述 500 codepoint。
    """
    if not skills:
        return ""

    # 按名称排序，最多 20 个
    sorted_skills = sorted(skills, key=lambda s: s.name)[:MAX_ENABLED_SKILLS]

    lines: list[str] = ["## 可用 Skills（按需调用 load_skill 加载完整指引）"]
    total_bytes = len(lines[0].encode("utf-8"))

    for skill in sorted_skills:
        desc = skill.description
        if len(desc) > MAX_DESCRIPTION_CODEPOINTS:
            desc = desc[:MAX_DESCRIPTION_CODEPOINTS] + "..."

        line = f"- **{skill.name}**: {desc}"
        line_bytes = len(line.encode("utf-8"))

        if total_bytes + line_bytes > MAX_INDEX_BYTES:
            sys.stderr.write(f"⚠️ 技能索引已达到 {MAX_INDEX_BYTES} 字节上限，已截断\n")
            break

        lines.append(line)
        total_bytes += line_bytes

    lines.append("\n调用 load_skill(name) 即可加载完整指引。\n判断准则：能用工具解决的问题不加载 Skill；同一个 Skill 不要重复加载。")

    return "\n".join(lines)
