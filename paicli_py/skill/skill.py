"""技能数据模型 —— 对应 ``com.paicli.skill.Skill`` record。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class SkillSource(Enum):
    """技能来源层级（内部枚举，与 Java Skill.Source 一致）。"""
    BUILTIN = "BUILTIN"
    USER = "USER"
    PROJECT = "PROJECT"


@dataclass
class Skill:
    """一个可加载的专家技能手册。"""
    name: str
    description: str = ""
    body: str = ""
    source: SkillSource = SkillSource.USER
    version: str = "1.0.0"
    author: str = ""
    tags: list[str] = field(default_factory=list)
    skill_md_path: Path | None = None
    references_dir: Path | None = None

    def __post_init__(self):
        """紧凑构造函数校验（与 Java 一致）。"""
        if not self.name or not self.name.strip():
            raise ValueError("技能名不能为空")

    def display_source(self) -> str:
        """返回来源的小写字符串（与 Java displaySource() 一致）。"""
        return self.source.value.lower()
