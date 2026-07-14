"""Project detection for Java Maven refactor-agent workflows."""

from __future__ import annotations

import shutil
import subprocess
import xml.etree.ElementTree as ET
from collections.abc import Callable, Sequence
from pathlib import Path

from suncli_py.refactor_agent.core.models import MavenModule, ProjectProfile

CommandRunner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]
PMD_PLUGIN_GROUP_ID = "org.apache.maven.plugins"
PMD_PLUGIN_ARTIFACT_ID = "maven-pmd-plugin"
PMD_PLUGIN_VERSION = "3.28.0"


def _default_command_runner(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    executable = shutil.which(command[0]) or command[0]
    return subprocess.run(
        [executable, *command[1:]],
        cwd=str(cwd),
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        text=True,
        timeout=15,
    )


class ProjectDetector:
    """Detect Git/Maven/Java/Test characteristics for the current repository."""

    def __init__(self, root: str | Path, command_runner: CommandRunner | None = None) -> None:
        self.root = Path(root).resolve()
        self._run = command_runner or _default_command_runner

    def detect(self) -> ProjectProfile:
        warnings: list[str] = []
        modules = self._detect_modules(warnings)
        root_has_main = (self.root / "src" / "main" / "java").is_dir()
        root_has_test = (self.root / "src" / "test" / "java").is_dir()

        is_git_repo = self._is_git_repo()
        is_git_clean = True
        if is_git_repo:
            is_git_clean = self._is_git_clean(warnings)
        else:
            warnings.append("当前目录不是 Git 仓库，未发现 .git。")

        is_maven_project = (self.root / "pom.xml").is_file()
        has_pmd_cpd_plugin = is_maven_project and self._has_pmd_cpd_plugin(self.root / "pom.xml")
        if not is_maven_project:
            warnings.append("当前目录不是 Maven 项目，未发现 pom.xml。")

        if not root_has_main and not any(module.has_main_java for module in modules):
            warnings.append("未发现 src/main/java。")
        if not root_has_test and not any(module.has_test_java for module in modules):
            warnings.append("未发现 src/test/java。")

        maven_version = self._read_command_version(["mvn", "-v"], warnings, "mvn -v")
        java_version = self._read_command_version(["java", "-version"], warnings, "java -version")

        return ProjectProfile(
            root=self.root,
            is_git_repo=is_git_repo,
            is_maven_project=is_maven_project,
            has_main_java=root_has_main or any(module.has_main_java for module in modules),
            has_test_java=root_has_test or any(module.has_test_java for module in modules),
            is_git_clean=is_git_clean,
            has_pmd_cpd_plugin=has_pmd_cpd_plugin,
            maven_version=maven_version,
            java_version=java_version,
            modules=modules,
            warnings=warnings,
        )

    def install_pmd_cpd_plugin(self) -> None:
        """Add the Maven PMD plugin to the root build after caller confirmation."""
        pom_path = self.root / "pom.xml"
        if not pom_path.is_file():
            raise ValueError("pom.xml does not exist")
        if self._has_pmd_cpd_plugin(pom_path):
            return

        parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
        tree = ET.parse(pom_path, parser=parser)
        project = tree.getroot()
        namespace = _namespace(project.tag)
        if namespace:
            ET.register_namespace("", namespace[1:-1])

        build = project.find(f"{namespace}build")
        if build is None:
            build = ET.SubElement(project, f"{namespace}build")
        plugins = build.find(f"{namespace}plugins")
        if plugins is None:
            plugins = ET.SubElement(build, f"{namespace}plugins")
        plugin = ET.SubElement(plugins, f"{namespace}plugin")
        ET.SubElement(plugin, f"{namespace}groupId").text = PMD_PLUGIN_GROUP_ID
        ET.SubElement(plugin, f"{namespace}artifactId").text = PMD_PLUGIN_ARTIFACT_ID
        ET.SubElement(plugin, f"{namespace}version").text = PMD_PLUGIN_VERSION

        ET.indent(tree, space="  ")
        tree.write(pom_path, encoding="utf-8", xml_declaration=True)

    @staticmethod
    def _has_pmd_cpd_plugin(pom_path: Path) -> bool:
        try:
            project = ET.parse(pom_path).getroot()
        except (ET.ParseError, OSError):
            return False
        namespace = _namespace(project.tag)
        build = project.find(f"{namespace}build")
        if build is None:
            return False
        plugins = build.find(f"{namespace}plugins")
        if plugins is None:
            return False
        return any(
            (plugin.findtext(f"{namespace}artifactId") or "").strip() == PMD_PLUGIN_ARTIFACT_ID
            and (plugin.findtext(f"{namespace}groupId") or PMD_PLUGIN_GROUP_ID).strip() == PMD_PLUGIN_GROUP_ID
            for plugin in plugins.findall(f"{namespace}plugin")
        )

    def _is_git_repo(self) -> bool:
        git_path = self.root / ".git"
        if git_path.exists():
            return True

        result = self._run_quiet(["git", "rev-parse", "--is-inside-work-tree"])
        return result is not None and result.returncode == 0 and result.stdout.strip().lower() == "true"

    def _is_git_clean(self, warnings: list[str]) -> bool:
        result = self._run_quiet(["git", "status", "--porcelain"])
        if result is None or result.returncode != 0:
            warnings.append("无法读取 Git 工作区状态。")
            return False

        if result.stdout.strip():
            warnings.append("Git 工作区不干净，存在未提交修改；后续 apply 前必须确认。")
            return False
        return True

    def _detect_modules(self, warnings: list[str]) -> list[MavenModule]:
        pom_path = self.root / "pom.xml"
        if not pom_path.is_file():
            return []

        try:
            tree = ET.parse(pom_path)
        except ET.ParseError:
            warnings.append("pom.xml 解析失败，无法识别多模块结构。")
            return []

        root = tree.getroot()
        namespace = ""
        if root.tag.startswith("{"):
            namespace = root.tag.split("}", 1)[0] + "}"

        modules: list[MavenModule] = []
        for module_node in root.findall(f".//{namespace}modules/{namespace}module"):
            module_name = (module_node.text or "").strip()
            if not module_name:
                continue
            module_path = (self.root / module_name).resolve()
            try:
                relative_path = str(module_path.relative_to(self.root))
            except ValueError:
                warnings.append(f"忽略越界 Maven module: {module_name}")
                continue
            modules.append(
                MavenModule(
                    name=module_name,
                    path=relative_path,
                    has_main_java=(module_path / "src" / "main" / "java").is_dir(),
                    has_test_java=(module_path / "src" / "test" / "java").is_dir(),
                )
            )
        return modules

    def _read_command_version(self, command: Sequence[str], warnings: list[str], label: str) -> str | None:
        result = self._run_quiet(command)
        if result is None:
            warnings.append(f"无法执行 {label}。")
            return None
        if result.returncode != 0:
            warnings.append(f"{label} 执行失败。")
            return None

        output = (result.stdout or result.stderr).strip()
        return output.splitlines()[0].strip() if output else None

    def _run_quiet(self, command: Sequence[str]) -> subprocess.CompletedProcess[str] | None:
        try:
            return self._run(command, self.root)
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            return None


def _namespace(tag: str) -> str:
    return tag.split("}", 1)[0] + "}" if tag.startswith("{") else ""
