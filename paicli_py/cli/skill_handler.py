"""技能命令处理器 —— 对应 ``com.paicli.cli.SkillCommandHandler``。

处理 /skill list, /skill show, /skill on, /skill off, /skill reload 命令。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from paicli_py.skill.registry import SkillRegistry
    from paicli_py.skill.state_store import SkillStateStore


def handle_skill_list(registry: SkillRegistry, state: SkillStateStore | None) -> str:
    """列出所有技能及其启用/禁用状态。"""
    skills = registry.list_all()
    if not skills:
        return "(无可用技能)"

    lines: list[str] = ["可用技能:"]
    for skill in skills:
        enabled = state.is_enabled(skill.name) if state else True
        status = "✅" if enabled else "❌"
        lines.append(f"  {status} {skill.display_name} — {skill.description[:80]}")
    return "\n".join(lines)


def handle_skill_show(registry: SkillRegistry, name: str) -> str:
    """显示单个技能的详细信息。"""
    skill = registry.get(name)
    if not skill:
        return f"未找到技能: {name}"

    lines = [
        f"技能: {skill.name}",
        f"描述: {skill.description}",
        f"版本: {skill.version}",
        f"作者: {skill.author}",
        f"标签: {', '.join(skill.tags) if skill.tags else '(无)'}",
        f"来源: {skill.source.value}",
        "---",
        skill.body[:2000],
    ]
    return "\n".join(lines)


def handle_skill_enable(state: SkillStateStore, name: str) -> str:
    """启用技能。"""
    state.enable(name)
    return f"✅ 已启用技能: {name}"


def handle_skill_disable(state: SkillStateStore, name: str) -> str:
    """禁用技能。"""
    state.disable(name)
    return f"✅ 已禁用技能: {name}"
