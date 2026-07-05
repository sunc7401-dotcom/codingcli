"""项目记忆初始化器 —— 生成 PAI.md 文件。

对应 ``com.paicli.cli.ProjectMemoryInitializer``。
"""

from __future__ import annotations

from pathlib import Path


class ProjectMemoryInitializer:
    """为项目生成 PAI.md 记忆文件。

    通过分析项目结构（build 系统、框架、测试框架等）自动生成。
    """

    PAI_MD_TEMPLATE = """# {project_name}

## 项目概览
- 语言: {language}
- 构建工具: {build_tool}
- 测试框架: {test_framework}

## 项目结构
```
{structure}
```

## 注意事项
- 请遵守项目现有的代码风格
- 修改代码前先阅读相关文件
"""

    @classmethod
    def generate(cls, project_dir: str | None = None, force: bool = False) -> str:
        """分析项目并生成 PAI.md。

        Returns:
            生成结果描述信息。
        """
        base = Path(project_dir).resolve() if project_dir else Path.cwd()
        pai_file = base / "PAI.md"

        if pai_file.exists() and not force:
            return f"PAI.md 已存在: {pai_file}（使用 --force 覆盖）"

        # 分析项目
        info = cls._analyze_project(base)

        # 生成内容
        content = cls.PAI_MD_TEMPLATE.format(
            project_name=base.name,
            language=info.get("language", "未知"),
            build_tool=info.get("build_tool", "未知"),
            test_framework=info.get("test_framework", "未知"),
            structure=cls._render_structure(base),
        )

        pai_file.write_text(content, encoding="utf-8")
        return f"✅ 已生成 {pai_file}"

    @staticmethod
    def _analyze_project(base: Path) -> dict[str, str]:
        """分析项目特征。"""
        info: dict[str, str] = {}

        # 语言检测
        if list(base.rglob("*.py")):
            info["language"] = "Python"
        elif list(base.rglob("*.java")):
            info["language"] = "Java"

        # 构建工具
        if (base / "pyproject.toml").exists():
            info["build_tool"] = "Poetry/setuptools"
        elif (base / "pom.xml").exists():
            info["build_tool"] = "Maven"

        # 测试框架
        if list(base.rglob("test_*.py")) or list(base.rglob("*_test.py")):
            info["test_framework"] = "pytest"
        elif (base / "tests").is_dir():
            info["test_framework"] = "pytest"

        return info

    @staticmethod
    def _render_structure(base: Path, max_depth: int = 3) -> str:
        """渲染项目结构树。"""
        lines: list[str] = []
        for path in sorted(base.iterdir()):
            if path.name.startswith(".") and path.name not in (".env",):
                continue
            if path.is_dir():
                lines.append(f"├── {path.name}/")
            else:
                lines.append(f"├── {path.name}")
        return "\n".join(lines[:30])
