"""技能注册表 —— 三层加载（内置 → 用户 → 项目）。

对应 ``com.paicli.skill.SkillRegistry``。
"""

from __future__ import annotations

from pathlib import Path

from paicli_py.skill.frontmatter_parser import parse_frontmatter
from paicli_py.skill.skill import Skill, SkillSource
from paicli_py.skill.state_store import SkillStateStore


class SkillRegistry:
    """三层技能注册表（与 Java 完全一致）。"""

    BUILTIN_CACHE_DIR: Path = Path.home() / ".paicli" / "skills-cache"
    USER_SKILLS_DIR: Path = Path.home() / ".paicli" / "skills"
    PROJECT_SKILLS_DIR_NAME: str = ".paicli/skills"

    def __init__(self, project_root: str | None = None, state_store: SkillStateStore | None = None,
                 builtin_cache: Path | None = None, user_dir: Path | None = None) -> None:
        self._skills: dict[str, Skill] = {}
        self._state_store = state_store or SkillStateStore()
        self._project_root = Path(project_root) if project_root else Path.cwd()
        self._builtin_cache = builtin_cache or self.BUILTIN_CACHE_DIR
        self._user_dir = user_dir or self.USER_SKILLS_DIR
        self._warnings: list[str] = []

    @property
    def state_store(self) -> SkillStateStore:
        return self._state_store

    @property
    def warnings(self) -> list[str]:
        return list(self._warnings)

    def reload(self) -> None:
        """重新扫描三层目录。"""
        self._skills.clear()
        self._warnings.clear()
        self._load_directory(self._builtin_cache, SkillSource.BUILTIN)
        self._load_directory(self._user_dir, SkillSource.USER)
        self._load_directory(self._project_root / self.PROJECT_SKILLS_DIR_NAME, SkillSource.PROJECT)

    def _load_directory(self, base_dir: Path, source: SkillSource) -> None:
        if not base_dir.is_dir():
            return
        for skill_dir in base_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.is_file():
                continue
            try:
                skill = self._load_skill_file(skill_md, source)
                self._skills[skill.name] = skill
            except Exception as e:
                self._warnings.append(f"加载失败 {skill_dir}: {e}")

    @staticmethod
    def _load_skill_file(skill_md_path: Path, source: SkillSource) -> Skill:
        text = skill_md_path.read_text(encoding="utf-8")
        fm, body, warnings = parse_frontmatter(text)
        refs_dir = skill_md_path.parent / "references"
        return Skill(
            name=fm.get("name", skill_md_path.parent.name),
            description=fm.get("description", "(无描述)"),
            body=body.strip(),
            source=source,
            version=fm.get("version", "1.0.0"),
            author=fm.get("author", ""),
            tags=fm.get("tags", []),
            skill_md_path=skill_md_path,
            references_dir=refs_dir if refs_dir.is_dir() else None,
        )

    def find_skill(self, name: str) -> Skill | None:
        """查找技能（尊重禁用状态）。"""
        disabled = self._state_store.disabled()
        skill = self._skills.get(name)
        if skill and skill.name in disabled:
            return None
        return skill

    def find_any_skill(self, name: str) -> Skill | None:
        """查找技能（忽略禁用状态）。"""
        return self._skills.get(name)

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def enabled_skills(self) -> list[Skill]:
        """列出所有启用的技能。"""
        disabled = self._state_store.disabled()
        return [s for s in self._skills.values() if s.name not in disabled]

    def list_all(self) -> list[Skill]:
        return sorted(self._skills.values(), key=lambda s: s.name)

    def list_enabled(self, disabled: set[str]) -> list[Skill]:
        return [s for s in self.list_all() if s.name not in disabled]

    def __len__(self) -> int:
        return len(self._skills)

    def __contains__(self, name: str) -> bool:
        return name in self._skills
