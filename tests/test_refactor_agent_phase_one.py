from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from suncli_py.refactor_agent.commands import RefactorAgentError, run_scan
from suncli_py.refactor_agent.project_detector import ProjectDetector


def _runner(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    del cwd
    if list(command) == ["git", "status", "--porcelain"]:
        return subprocess.CompletedProcess(command, 0, stdout=" M src/main/java/Demo.java\n", stderr="")
    if list(command) == ["mvn", "-v"]:
        return subprocess.CompletedProcess(command, 0, stdout="Apache Maven 3.9.9\nJava version: 21\n", stderr="")
    if list(command) == ["java", "-version"]:
        return subprocess.CompletedProcess(command, 0, stdout="", stderr='openjdk version "21.0.1"\n')
    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


def test_project_detector_builds_profile_for_maven_git_project(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "src" / "main" / "java").mkdir(parents=True)
    (tmp_path / "module-a" / "src" / "test" / "java").mkdir(parents=True)
    (tmp_path / "pom.xml").write_text(
        """
        <project xmlns="http://maven.apache.org/POM/4.0.0">
          <modules>
            <module>module-a</module>
          </modules>
        </project>
        """,
        encoding="utf-8",
    )

    profile = ProjectDetector(tmp_path, command_runner=_runner).detect()

    assert profile.is_git_repo is True
    assert profile.is_maven_project is True
    assert profile.has_main_java is True
    assert profile.has_test_java is True
    assert profile.is_git_clean is False
    assert profile.has_pmd_cpd_plugin is False
    assert profile.maven_version == "Apache Maven 3.9.9"
    assert profile.java_version == 'openjdk version "21.0.1"'
    assert len(profile.modules) == 1
    assert "Git 工作区不干净" in "\n".join(profile.warnings)


def test_scan_reports_non_maven_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)

    with pytest.raises(RefactorAgentError, match="不是 Maven 项目"):
        run_scan()


def test_scan_json_outputs_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "src" / "main" / "java").mkdir(parents=True)
    (tmp_path / "pom.xml").write_text(
        """
<project>
  <modelVersion>4.0.0</modelVersion>
  <groupId>demo</groupId>
  <artifactId>sample</artifactId>
  <version>1.0.0</version>
  <build>
    <plugins>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-pmd-plugin</artifactId>
        <version>3.28.0</version>
      </plugin>
    </plugins>
  </build>
</project>
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    exit_code = run_scan(output_format="json", llm_assistant=_FakeTriageAssistant())

    assert exit_code == 0
    output = capsys.readouterr().out
    assert '"is_git_repo": true' in output
    assert '"is_maven_project": true' in output
    assert '"has_pmd_cpd_plugin": true' in output


def test_project_detector_installs_required_pmd_plugin(tmp_path: Path) -> None:
    pom_path = tmp_path / "pom.xml"
    pom_path.write_text(
        """
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <build>
    <pluginManagement>
      <plugins>
        <plugin>
          <artifactId>maven-pmd-plugin</artifactId>
        </plugin>
      </plugins>
    </pluginManagement>
  </build>
</project>
""".strip(),
        encoding="utf-8",
    )
    detector = ProjectDetector(tmp_path, command_runner=_runner)

    assert detector.detect().has_pmd_cpd_plugin is False
    detector.install_pmd_cpd_plugin()

    profile = detector.detect()
    installed_pom = pom_path.read_text(encoding="utf-8")
    assert profile.has_pmd_cpd_plugin is True
    assert "<version>3.28.0</version>" in installed_pom


def test_scan_prompts_before_installing_pmd_plugin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "pom.xml").write_text(
        """
<project>
  <modelVersion>4.0.0</modelVersion>
  <groupId>demo</groupId>
  <artifactId>sample</artifactId>
  <version>1.0.0</version>
</project>
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("suncli_py.refactor_agent.commands.sys.stdin.isatty", lambda: True)
    answers = iter(["yes", "yes"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    class EmptyScanner:
        def __init__(self, root: Path) -> None:
            del root
            self.warnings: list[str] = []

        def scan(self) -> list:
            return []

    monkeypatch.setattr("suncli_py.refactor_agent.commands.JavaSmellScanner", EmptyScanner)

    assert run_scan(llm_assistant=_FakeTriageAssistant()) == 0
    assert ProjectDetector(tmp_path, command_runner=_runner).detect().has_pmd_cpd_plugin is True


class _FakeTriageAssistant:
    def triage_issues(self, root: Path, issues: list) -> list:
        del root
        return issues
