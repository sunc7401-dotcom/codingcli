"""内置技能提取器 —— 从包资源中解压内置技能。

对应 ``com.paicli.skill.SkillBuiltinExtractor``。
"""

from __future__ import annotations

import shutil
from importlib import resources
from pathlib import Path


class SkillBuiltinExtractor:
    """将内置技能从包数据提取到 ~/.paicli/skills-cache/。

    使用 .version 文件进行缓存失效判断。
    """

    CACHE_DIR: Path = Path.home() / ".paicli" / "skills-cache"
    VERSION_FILE: str = ".version"
    CURRENT_VERSION: str = "1.0.0"

    @classmethod
    def extract_all(cls) -> None:
        """提取所有内置技能到缓存目录（按技能检查版本，与 Java 一致）。"""
        cls.CACHE_DIR.mkdir(parents=True, exist_ok=True)

        try:
            skills_dir = resources.files("suncli_py") / "resources" / "skills"
            if not skills_dir.is_dir():
                return
            for skill_dir in skills_dir.iterdir():
                if not skill_dir.is_dir():
                    continue
                skill_name = skill_dir.name
                cache_skill_dir = cls.CACHE_DIR / skill_name
                version_file = cache_skill_dir / cls.VERSION_FILE

                # 检查版本
                if version_file.is_file():
                    if version_file.read_text(encoding="utf-8").strip() == cls.CURRENT_VERSION:
                        continue
                    shutil.rmtree(str(cache_skill_dir))

                cache_skill_dir.mkdir(parents=True, exist_ok=True)
                # 复制技能文件
                for item in skill_dir.iterdir():
                    dest = cache_skill_dir / item.name
                    if item.is_dir():
                        shutil.copytree(str(item), str(dest), dirs_exist_ok=True)
                    else:
                        shutil.copy2(str(item), str(dest))
                # 写入版本
                version_file.write_text(cls.CURRENT_VERSION, encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def _copy_package_resources() -> None:
        """从 suncli_py/resources/skills/ 复制内置技能。

        如果包资源不存在（开发环境），则跳过。
        """
        try:
            # Python 3.9+ importlib.resources.files
            skills_dir = resources.files("suncli_py") / "resources" / "skills"
            if skills_dir.is_dir():
                shutil.copytree(str(skills_dir), str(SkillBuiltinExtractor.CACHE_DIR), dirs_exist_ok=True)
        except Exception:
            # 开发环境中可能没有 resources/skills 目录
            pass
